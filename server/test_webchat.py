"""웹 「대화」 전송 골격 시험(2026-11-04 PR 1) — 실제 uvicorn(스레드) + 장치 WS(agent/wsclient) + SSE(http.client) + 합성 PG.

실행: DATABASE_URL=postgresql://localhost/crm_test_webchat python3 server/test_webchat.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

다루는 것: 스위치 꺼짐 503(API·SSE·WS) · 세션(장치 자동·여러 대·없음) · 턴 멱등·TURN-BUSY·DEVICE-OFFLINE · (turn_id,seq) 중복 무시·빈 칸
· 누적 ack · SSE 재생·Last-Event-ID 재개·사용자당 1 · WS 인증(무토큰·틀림·철회·다른 사용자 턴 거절) · 중지 · 한도(글자·분당·이벤트·WS 64KB)
· 유휴 턴 TURN-TIMEOUT · 30일 삭제 · 계정 삭제 cascade · 응답에 남의 데이터 없음
· grant 요청, 상태 조회(GET), PC 거절 알림(consent.result), 동의 키, challenge HTTP route(세션 401·Origin 403·Bearer 401·바인딩 409·엄격 JSON·4KB·native 서명 뒤 approved, provider fail-closed).
"""
import asyncio
import http.client
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_webchat). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = ""
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_SESSION_SECRET"] = "webchat-test-secret"
os.environ.pop("CRM_WEBCHAT_ENABLED", None)
os.environ.pop("CRM_CHAT_MCP_ENABLED", None)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

import db  # noqa: E402
import facade  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import webchat  # noqa: E402
import features  # noqa: E402

# 조직 기능 설정 첫 시드(2026-11-12)는 test_admin_profiles.py 가 본다. 이 파일의 시험 서버(uvicorn)는 lifespan 을 도는데, 그때 시드하면
# (env 스위치는 비어 있다) 뒤 env 스위치("1")가 조직 꺼짐에 막힌다 — 조직 설정 행이 없을 때만 env 가 판정한다
features.seed_org_from_env = lambda: []
from agent import chat as agent_chat  # noqa: E402
from agent import wsclient  # noqa: E402

EMAILS = ("wc-a@example.com", "wc-b@example.com", "wc-rate@example.com", "wc-del@example.com", "wc-rev@example.com",
          "wc-permit@example.com", "wc-permit-b@example.com", "wc-link@example.com")
N = 0


def ok(msg):
    global N
    N += 1
    print(f"ok {N} - {msg}", flush=True)


def switch(on: bool):
    if on:
        os.environ["CRM_WEBCHAT_ENABLED"] = "1"
    else:
        os.environ.pop("CRM_WEBCHAT_ENABLED", None)


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


# ── 서버(스레드) ───────────────────────────────────────

class Server:
    def __init__(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=self.port, log_level="warning", ws="websockets"))
        self.th = threading.Thread(target=self.srv.run, daemon=True)

    def __enter__(self):
        self.th.start()
        for _ in range(200):
            if self.srv.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("서버가 뜨지 않음")

    def __exit__(self, *a):
        self.srv.should_exit = True
        self.th.join(10)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws(self):
        return f"ws://127.0.0.1:{self.port}/api/device/chat/ws"


def web(srv, uid=None, origin=True):
    h = httpx.Client(base_url=srv.base, headers={"origin": PUBLIC} if origin else {}, timeout=10)
    if uid:
        h.cookies.set("crm_session", main.site.session_value(uid))
    return h


class PC:
    """손으로 모는 장치 WS — 받은 메시지를 큐에 모은다(시험이 PC 역할)."""

    def __init__(self, srv, token, v2=True, capabilities=None):
        self.ws = wsclient.connect(srv.ws, {"Authorization": "Bearer " + token}, timeout=5)
        self.inbox, self.closed = [], None
        self.cv = threading.Condition()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()
        hello = {"type": "hello", "agent_version": "test", "providers": ["fake"]}
        if v2:
            hello.update({"capabilities_version": 2, "capabilities": capabilities or [{"provider": "fake", "models": [None, "fake-test"]}]})
        self.send(hello)

    def _loop(self):
        while True:
            try:
                m = json.loads(self.ws.recv())
            except wsclient.WsError as e:
                with self.cv:
                    self.closed = e.code if e.kind == "closed" else e.kind
                    self.cv.notify_all()
                return
            with self.cv:
                self.inbox.append(m)
                self.cv.notify_all()

    def send(self, m):
        self.ws.send_text(json.dumps(m, ensure_ascii=False))

    def event(self, tid, seq, kind, data):
        self.send({"type": "event", "turn_id": tid, "seq": seq, "kind": kind, "data": data})

    def wait(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                for i, m in enumerate(self.inbox):
                    if pred(m):
                        return self.inbox.pop(i)
                left = end - time.monotonic()
                if left <= 0 or self.closed is not None:
                    return None
                self.cv.wait(left)

    def ack(self, tid, timeout=5.0):
        m = self.wait(lambda m: m.get("type") == "ack" and m.get("turn_id") == tid, timeout)
        return m and m["seq"]

    def wait_closed(self, timeout=5.0):
        end = time.monotonic() + timeout
        with self.cv:
            while self.closed is None and time.monotonic() < end:
                self.cv.wait(0.1)
            return self.closed

    def close(self):
        self.ws.close()


class SSE:
    def __init__(self, srv, uid, sid, last_id=None):
        self.c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        h = {"cookie": "crm_session=" + main.site.session_value(uid), "accept": "text/event-stream"}
        if last_id:
            h["last-event-id"] = last_id
        self.c.request("GET", f"/api/chat/sessions/{sid}/stream", headers=h)
        self.r = self.c.getresponse()
        self.status = self.r.status
        self.headers = dict((k.lower(), v) for k, v in self.r.getheaders())

    def next(self, timeout=5.0):
        """다음 SSE 항목 {id, event, data} · 주석(heartbeat)은 건너뜀 · 끝 = None."""
        self.c.sock.settimeout(timeout)
        cur = {}
        while True:
            try:
                line = self.r.readline()
            except socket.timeout:
                return "timeout"
            if not line:
                return None
            line = line.decode("utf-8").rstrip("\r\n")
            if line == "":
                if "event" in cur:
                    return cur
                cur = {}
                continue
            if line.startswith(":"):
                cur.setdefault("comments", 0)
                continue
            k, _, v = line.partition(": ")
            if k == "data":
                v = json.loads(v)
            cur[k] = v

    def until(self, event, timeout=5.0):
        out = []
        while True:
            e = self.next(timeout)
            if e in (None, "timeout"):
                return out, e
            out.append(e)
            if e["event"] == event:
                return out, e

    def close(self):
        self.c.close()


def rows(sql, args=()):
    with db.tx() as c:
        return c.execute(sql, args).fetchall()


def test_chat_session_migration(uid, device_id):
    sid = webchat._id("cs")
    with db.tx() as c:
        c.execute("INSERT INTO chat_sessions (id,user_id,device_id,status) VALUES (%s,%s,%s,'closed')", (sid, uid, device_id))
        c.execute("ALTER TABLE chat_sessions DROP COLUMN model, DROP COLUMN client_session_id, DROP COLUMN binding_version")
    db.init_schema()
    db.init_schema()
    cols = {r["column_name"] for r in rows("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='chat_sessions'")}
    assert {"model", "client_session_id", "binding_version"} <= cols, cols
    row = rows("SELECT user_id,device_id,status,model,client_session_id,binding_version FROM chat_sessions WHERE id=%s", (sid,))[0]
    assert row == {"user_id": uid, "device_id": device_id, "status": "closed", "model": None, "client_session_id": None, "binding_version": 0}, row
    idx = {r["indexname"] for r in rows("SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() AND tablename='chat_sessions'")}
    assert "ux_chat_sessions_client" in idx, idx
    with db.tx() as c:
        c.execute("DELETE FROM chat_sessions WHERE id=%s", (sid,))
    ok("chat_sessions 이전 스키마: 기존 행 보존 + null/0 backfill + partial unique index + init_schema 멱등")


# ── 시험 ───────────────────────────────────────────────

def test_static():
    assert "WEBCHAT_ENABLED" in __import__("envnames").SWITCHES
    assert "chat_sessions" in db.DELETE_TABLES
    src = (HERE / "webchat.py").read_text(encoding="utf-8")
    assert "print(" not in src, "본문·토큰 로그 자리 없음 — webchat.py 는 print 하지 않는다"
    assert "websockets" in (HERE / "requirements.txt").read_text()
    ok("정적: 스위치 이름 · 삭제 목록 chat_sessions · webchat.py 로그 0 · websockets 의존성")
    sub = webchat._Sub("u1", "cs_1")
    sub.put(("a:1", b"x"), webchat.LIVE_BUFFER_BYTES - 10)
    assert not sub.closed.is_set()
    sub.put(("a:2", b"y"), 11)
    assert sub.closed.is_set() and sub.q.qsize() == 2 and sub.q.get_nowait()[0] == ("a:1", b"x") and sub.q.get_nowait() == ("close", None), "넘치면 닫고 깨움"
    h = webchat.Hub()
    h.subs["u1"] = webchat._Sub("u1", "cs_1")
    h.publish("u1", "cs_other", "ct_x:1", "delta", {})
    h.publish("u2", "cs_1", "ct_x:1", "delta", {})
    assert h.subs["u1"].q.qsize() == 0, "남의 세션·사용자 항목은 구독에 안 들어간다"
    ok(f"라이브 버퍼: 구독당 {webchat.LIVE_BUFFER_BYTES // 1024}KB 넘으면 닫음(클라이언트 재생) · 발행은 그 사용자·그 세션 구독에만")


def test_switch_off(srv, ua, tok_a):
    switch(False)
    with web(srv, ua) as h:
        for r in (h.post("/api/chat/sessions", json={}), h.get("/api/chat/sessions"), h.get("/api/chat/sessions/cs_x/stream"),
                  h.post("/api/chat/sessions/cs_x/turns", json={"text": "a", "client_turn_id": "c1"}), h.get("/api/chat/grants/route-x")):
            assert r.status_code == 503 and r.json()["code"] == "SWITCH-OFF", (r.status_code, r.text)
    try:
        wsclient.connect(srv.ws, {"Authorization": "Bearer " + tok_a}, timeout=5)
        raise AssertionError("꺼짐인데 WS 가 열림")
    except wsclient.WsError as e:
        assert e.kind == "handshake" and e.status == 503 and e.code == "SWITCH-OFF", e
    with web(srv, ua) as h:
        assert h.get("/api/state").json()["switches"]["webchat"] is False
    switch(True)
    with web(srv, ua) as h:
        assert h.get("/api/state").json()["switches"]["webchat"] is True
    ok("스위치 꺼짐 = API·SSE·턴 503 SWITCH-OFF · WS 핸드셰이크 503 · /api/state switches.webchat")


def test_gate(srv, ua):
    with web(srv) as h:
        r = h.post("/api/chat/sessions", json={})
        assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"
        r = h.get("/api/chat/grants/route-x")
        assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"
    with web(srv, ua, origin=False) as h:
        r = h.post("/api/chat/sessions", json={})
        assert r.status_code == 403 and r.json()["code"] == "ORIGIN"
    ok("세션 없음 401 · POST Origin 없음 403")


def test_ws_auth(srv, tok_a, revoked_tok):
    for hdr, code in (({}, "AUTH-INVALID"), ({"Authorization": "Bearer imp_is_x.it_y.zzz"}, "AUTH-INVALID"),
                      ({"Authorization": "Bearer " + revoked_tok}, "TOKEN-REVOKED")):
        try:
            wsclient.connect(srv.ws, hdr, timeout=5)
            raise AssertionError("열리면 안 됨")
        except wsclient.WsError as e:
            assert e.kind == "handshake" and e.status == 401 and e.code == code, (e, code)
    ws = wsclient.connect(srv.ws, {"Authorization": "Bearer " + tok_a}, timeout=5)
    ws.close()
    ok("WS 인증: 무토큰·틀린 토큰 401 AUTH-INVALID · 철회 토큰 401 TOKEN-REVOKED · 유효 토큰 101")


def test_v2_capabilities(srv, ua, tok_a, dev_a):
    pc = PC(srv, tok_a)
    try:
        time.sleep(0.15)
        with web(srv, ua) as h:
            r = h.get("/api/chat/capabilities")
            assert r.status_code == 200, r.text
            assert r.headers.get("cache-control") == "no-store"
            body = r.json()
            assert body["devices"] == [{"device_id": dev_a, "connected": True, "agent_version": "test",
                                         "capabilities_version": 2,
                                         "capabilities": [{"provider": "fake", "models": [None, "fake-test"]}],
                                         "allowed_providers": [], "ai_links": None}], body
            assert body["setup"] == "ready", body
        ok("v2 capability: 인증된 사용자 live 장치만 no-store 로 모델 capability 제공")
    finally:
        pc.close()
    legacy = PC(srv, tok_a, v2=False)
    try:
        time.sleep(0.15)
        with web(srv, ua) as h:
            assert h.get("/api/chat/capabilities").json() == {"devices": [], "setup": "no_provider"}, "기존 hello는 v2 capability로 승격하지 않는다"
            sid = h.post("/api/chat/sessions", json={}).json()["session_id"]
            r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "legacy", "client_turn_id": "legacy-block"})
            assert r.status_code == 409 and r.json()["code"] == "PROVIDER-UNAVAILABLE", r.text
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev_a, "provider": "fake", "model": None, "client_session_id": "invalid-legacy-v2"})
            assert r.status_code == 409 and r.json()["code"] == "PROVIDER-UNAVAILABLE", r.text
        ok("구형 hello는 v2 capability 승격 불가 · 구형 세션은 replay 가능하나 새 턴 불가")
    finally:
        legacy.close()


def test_consent_fail_closed(srv, ua, tok_a, dev_a):
    caps = [{"provider": "claude", "models": [None, "test-model"]}]
    pc = PC(srv, tok_a, capabilities=caps)
    sid = None
    try:
        time.sleep(0.15)
        with web(srv, ua) as h:
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev_a, "provider": "claude", "model": "test-model", "client_session_id": "consent-new-denied"})
            assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED", r.text
            assert rows("SELECT count(*) AS n FROM chat_sessions WHERE user_id=%s AND client_session_id='consent-new-denied'", (ua,))[0]["n"] == 0
            sid = webchat._id("cs")
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET status='closed' WHERE user_id=%s AND status='active'", (ua,))
                c.execute("INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version) VALUES (%s,%s,%s,'claude','test-model','consent-existing-denied',2)", (sid, ua, dev_a))
            r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "승인 없는 턴", "client_turn_id": "consent-turn-denied"})
            assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED", r.text
            assert rows("SELECT count(*) AS n FROM chat_turns WHERE session_id=%s", (sid,))[0]["n"] == 0
        ok("v2 Claude: consent proof 미구현 상태에서 세션 생성·턴 실행 모두 CONSENT_REQUIRED")
    finally:
        pc.close()
        if sid:
            with db.tx() as c:
                c.execute("DELETE FROM chat_sessions WHERE id=%s", (sid,))


def _code(fn):
    try:
        fn()
    except db.CrmError as e:
        return e.code
    raise AssertionError("CrmError 가 나야 해요")


def test_consent_bind_empty_device(srv, ua, ub):
    """2026-11-13: 장치 토큰을 손으로 넣은 PC 는 설치본 device_id 가 비어 있어 키 등록 시작(begin)이 매번 409 CONSENT_REQUIRED 였다.
    usage 집계는 이 code 를 EXC 로 센다(밑줄은 web._usage 의 code 형식 밖). begin 만 빈 설치본을 요청 장치로 처음 한 번 묶는다.
    합성 장치·합성 설치본만."""
    import base64
    import secrets
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import consent_signature

    def b64(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def der(k):
        return k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    def sign(k, claims):
        return b64(k.sign(consent_signature.encode_consent(claims)))

    def inst_dev(i):
        return rows("SELECT device_id FROM desktop_installations WHERE user_id=%s AND id=%s", (ua, i))[0]["device_id"]

    def usage(code):
        return sum(n for (_d, u, name, cd), n in db.usage_snapshot().items()
                   if u == ua and name == "web:chat_consent_key_begin" and cd == code)

    BEGIN = "/api/chat/consent/keys/begin"
    d1, d2, d3 = (imports.device_connect(ua, f"bind pc{n}") for n in (1, 2, 3))
    gone = imports.device_connect(ua, "bind pc gone")
    imports.device_revoke(ua, gone["device"]["id"])
    foreign = imports.device_connect(ub, "b bind pc")
    b1, b3 = "Bearer " + d1["token"], "Bearer " + d3["token"]
    i_null, i_blank, i_bound, i_revoked, i_held = ("di_" + secrets.token_hex(12) for _ in range(5))
    k1, k2 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    try:
        with db.tx() as c:
            for i, d in ((i_null, None), (i_blank, ""), (i_bound, d2["device"]["id"]), (i_revoked, None), (i_held, None)):
                c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'bind pc','darwin',%s)", (ua, i, d))
            c.execute("UPDATE desktop_installations SET revoked_at=now() WHERE user_id=%s AND id=%s", (ua, i_revoked))

        # 고치기 전 동작 재현: 빈 설치본은 묶음 검사 마지막 줄(device_id != 토큰 장치)에서 CONSENT_REQUIRED
        with db.tx() as c:
            webchat._user_lock(c, ua)
            dev1 = imports.authenticate(b1)
            assert _code(lambda: webchat._consent_bind(c, ua, dev1, i_null)) == "CONSENT_REQUIRED"
        assert inst_dev(i_null) is None
        # 그 409 CONSENT_REQUIRED 를 usage 는 EXC 로 센다(예외가 아니다) — 다른 장치에 묶인 설치본으로 같은 응답을 본다
        before = usage("EXC")
        with web(srv, ua) as h:
            r = h.post(BEGIN, json={"installation_id": i_bound, "spki": b64(der(k1))}, headers={"authorization": b1})
        assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED", r.text
        assert usage("EXC") == before + 1 and inst_dev(i_bound) == d2["device"]["id"]
        ok("동의 키 묶음: 빈 설치본 거절은 409 CONSENT_REQUIRED, usage 는 그 code 를 EXC 로 센다")

        # 다른 사용자 토큰·해제된 장치 토큰·해제된 설치본·begin 이 아닌 호출은 빈 설치본을 묶지 않는다
        assert _code(lambda: webchat.consent_key_begin(ua, "Bearer " + foreign["token"], i_null, der(k1))) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.consent_key_begin(ub, b1, i_null, der(k1))) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.consent_key_begin(ua, "Bearer " + gone["token"], i_null, der(k1))) != "OK"
        assert _code(lambda: webchat.consent_key_begin(ua, b1, i_revoked, der(k1))) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.consent_key_revoke_bound(ua, b1, i_null)) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.consent_challenge_issue(ua, b1, i_null, "bind-r0")) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.consent_key_activate(ua, b1, i_null, "ck_" + "0" * 24, "A" * 86)) == "CONSENT_REQUIRED"
        assert (inst_dev(i_null), inst_dev(i_revoked)) == (None, None)
        ok("동의 키 묶음: 남의 토큰·다른 세션·해제된 장치·해제된 설치본·begin 밖 호출은 묶지 않는다")

        # NULL 설치본: begin(route) 이 요청 장치로 묶고, 그 뒤 activate → grant → issue → verify 가 끝까지 간다
        ok_before = usage("OK")
        with web(srv, ua) as h:
            r = h.post(BEGIN, json={"installation_id": i_null, "spki": b64(der(k1))}, headers={"authorization": b1})
        assert r.status_code == 200, r.text
        assert usage("OK") == ok_before + 1 and inst_dev(i_null) == d1["device"]["id"]
        b = r.json()
        assert webchat.consent_key_activate(ua, b1, i_null, b["key_id"], sign(k1, b["claims"]))["state"] == "active"
        webchat.grant_request(ua, d1["device"]["id"], "claude", "test-model", "bind-r1")
        cl = webchat.consent_challenge_issue(ua, b1, i_null, "bind-r1")["claims"]
        assert cl["device_id"] == d1["device"]["id"]
        assert webchat.consent_challenge_verify(ua, b1, i_null, cl["nonce"], sign(k1, cl))["state"] == "verified"
        # 한 번 묶이면 다른 장치는 거절, 같은 장치의 다음 begin 은 그대로 통과
        assert _code(lambda: webchat.consent_key_begin(ua, b3, i_null, der(k2))) == "CONSENT_REQUIRED"
        assert inst_dev(i_null) == d1["device"]["id"]
        # 이미 살아 있는 설치본에 묶인 장치는 두 번째 빈 설치본을 묶지 못한다(장치 하나 = PC 하나)
        assert _code(lambda: webchat.consent_key_begin(ua, b1, i_held, der(k2))) == "CONSENT_REQUIRED"
        assert inst_dev(i_held) is None
        ok("동의 키 묶음: 빈(NULL) 설치본은 begin 이 요청 장치로 처음 한 번 묶고 동의가 끝까지 간다, 다른 장치 재묶음·장치 중복 묶음 거절")

        # 빈 문자열 설치본도 빈 것으로 본다
        b = webchat.consent_key_begin(ua, b3, i_blank, der(k2))
        assert b["claims"]["device_id"] == d3["device"]["id"] and inst_dev(i_blank) == d3["device"]["id"]
        ok("동의 키 묶음: 빈 문자열 device_id 설치본도 begin 이 묶는다")
    finally:
        installs = [i_null, i_blank, i_bound, i_revoked, i_held]
        with db.tx() as c:
            c.execute("DELETE FROM chat_consent_challenges WHERE user_id=%s AND installation_id = ANY(%s)", (ua, installs))
            c.execute("DELETE FROM chat_provider_grants WHERE user_id=%s AND request_id LIKE 'bind-r%%'", (ua,))
            c.execute("DELETE FROM desktop_consent_keys WHERE user_id=%s AND installation_id = ANY(%s)", (ua, installs))
            c.execute("DELETE FROM desktop_installations WHERE user_id=%s AND id = ANY(%s)", (ua, installs))
        for d in (d1, d2, d3):
            imports.device_revoke(ua, d["device"]["id"])
        imports.device_revoke(ub, foreign["device"]["id"])


def _grant_state(uid, rid):
    return rows("SELECT state FROM chat_provider_grants WHERE user_id=%s AND request_id=%s", (uid, rid))[0]["state"]


def _grant_consume(uid, dev, provider, model, rid):
    with db.tx() as c:
        return webchat.grant_consume(c, uid, dev, provider, model, rid)


def test_grant_fail_closed(ua, ub, dev_a):
    """PC 명시 승인 grant 기반 — 저장·바인딩·만료·단회 소비. 신뢰할 desktop verifier 가 없으면 승인·소비 모두 CONSENT_REQUIRED."""
    assert webchat._desktop_verifier is None   # 운영 기본 = 검증 수단 없음
    try:
        g, created = webchat.grant_request(ua, dev_a, "claude", "test-model", "grant-r1")
        assert created and g["state"] == "pending" and g["expires_at"] > g["created_at"], g
        assert (g["user_id"], g["device_id"], g["provider"], g["model"], g["request_id"]) == (ua, dev_a, "claude", "test-model", "grant-r1"), g
        g2, created2 = webchat.grant_request(ua, dev_a, "claude", "test-model", "grant-r1")
        assert not created2 and g2["id"] == g["id"]
        assert _code(lambda: webchat.grant_request(ua, dev_a, "codex", "test-model", "grant-r1")) == "GRANT-CONFLICT"
        assert _code(lambda: webchat.grant_request(ua, dev_a, "claude", None, "grant-r1")) == "GRANT-CONFLICT"
        assert _code(lambda: webchat.grant_request(ua, dev_a, "fake", None, "grant-r-fake")) == "ARG-INVALID"
        assert _code(lambda: webchat.grant_request(ua, dev_a, "claude", None, "bad id!")) == "ARG-INVALID"
        assert _code(lambda: webchat.grant_request(ua, "dev_nope", "claude", None, "grant-r-dev")) == "NOT-FOUND"
        assert _code(lambda: webchat.grant_request(ub, dev_a, "claude", None, "grant-r-ub")) == "NOT-FOUND"   # 남의 장치
        ok("grant 요청: 사용자·장치·provider·model·request_id 바인딩 저장, 같은 요청 멱등·다른 바인딩 GRANT-CONFLICT")

        # verifier 없음 → 승인 불가. Origin 부재·X-MyCRM-Desktop 표식을 proof 로 넘겨도 증거가 아니다
        for proof in (None, {}, {"origin": None}, {"X-MyCRM-Desktop": "1"}, {"headers": {"X-MyCRM-Desktop": "1"}}, True):
            assert _code(lambda: webchat.grant_approve(ua, "grant-r1", proof)) == "CONSENT_REQUIRED", proof
        assert _grant_state(ua, "grant-r1") == "pending"
        # 옛 빌드·수동으로 approved 가 된 행도 verifier 없이는 소비하지 않는다
        with db.tx() as c:
            c.execute("UPDATE chat_provider_grants SET state='approved', approved_at=now() WHERE user_id=%s AND request_id='grant-r1'", (ua,))
        assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "grant-r1")) == "CONSENT_REQUIRED"
        assert _grant_state(ua, "grant-r1") == "approved"
        ok("grant: desktop verifier 없으면 승인·소비 모두 CONSENT_REQUIRED(머리글 표식 무시·상태 변화 없음)")

        # 시험 전용 가짜 verifier 는 grant 를 approved 로 표시할 수 있지만, verified Ed25519 challenge 없이는 세션 소비가 안 된다.
        seen = []

        def fake_verifier(uid, binding, proof):
            seen.append((uid, binding["request_id"], binding["device_id"], binding["provider"], binding["model"]))
            return proof == "synthetic-ok"

        webchat._desktop_verifier = fake_verifier
        assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "grant-r-none")) == "CONSENT_REQUIRED"
        webchat.grant_request(ua, dev_a, "claude", "test-model", "grant-r2")
        assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "grant-r2")) == "CONSENT_REQUIRED"   # 미승인
        assert _code(lambda: webchat.grant_approve(ua, "grant-r2", "wrong")) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.grant_approve(ua, "grant-r2", "1")) == "CONSENT_REQUIRED"
        assert _grant_state(ua, "grant-r2") == "pending"
        assert _code(lambda: webchat.grant_approve(ub, "grant-r2", "synthetic-ok")) == "NOT-FOUND"   # 다른 사용자
        assert webchat.grant_approve(ua, "grant-r2", "synthetic-ok")["state"] == "approved"
        assert (ua, "grant-r2", dev_a, "claude", "test-model") in seen
        assert _code(lambda: webchat.grant_approve(ua, "grant-r2", "synthetic-ok")) == "GRANT-USED"
        for args, expected in (((ub, dev_a, "claude", "test-model", "grant-r2"), "CONSENT_REQUIRED"),
                               ((ua, "dev_other", "claude", "test-model", "grant-r2"), "GRANT-INVALID"),
                               ((ua, dev_a, "codex", "test-model", "grant-r2"), "GRANT-INVALID"),
                               ((ua, dev_a, "claude", "other-model", "grant-r2"), "GRANT-INVALID"),
                               ((ua, dev_a, "claude", None, "grant-r2"), "GRANT-INVALID"),
                               ((ua, dev_a, "claude", "test-model", "grant-r9"), "CONSENT_REQUIRED")):
            assert _code(lambda: _grant_consume(*args)) == expected, (args, expected)
        assert _grant_state(ua, "grant-r2") == "approved"
        try:   # 소비는 호출한 쪽 트랜잭션과 같이 롤백된다
            with db.tx() as c:
                assert _code(lambda: webchat.grant_consume(c, ua, dev_a, "claude", "test-model", "grant-r2")) == "CONSENT_REQUIRED"
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        assert _grant_state(ua, "grant-r2") == "approved"
        assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "grant-r2")) == "CONSENT_REQUIRED"
        assert _grant_state(ua, "grant-r2") == "approved"
        ok("generic verifier approval is insufficient: without a verified active-key challenge grant consumption fails closed")

        webchat.grant_request(ua, dev_a, "codex", None, "grant-r3")
        webchat.grant_approve(ua, "grant-r3", "synthetic-ok")
        webchat.grant_request(ua, dev_a, "codex", None, "grant-r4")
        with db.tx() as c:
            c.execute("UPDATE chat_provider_grants SET created_at=now()-interval '10 minutes', expires_at=now()-interval '5 minutes' "
                      "WHERE user_id=%s AND request_id IN ('grant-r3','grant-r4')", (ua,))
        assert _code(lambda: _grant_consume(ua, dev_a, "codex", None, "grant-r3")) == "GRANT-EXPIRED"
        assert _grant_state(ua, "grant-r3") == "approved"
        assert _code(lambda: webchat.grant_approve(ua, "grant-r4", "synthetic-ok")) == "GRANT-EXPIRED"
        assert _grant_state(ua, "grant-r4") == "pending"
        assert [webchat.grant_status(ua, r)["state"] for r in ("grant-r3", "grant-r4")] == ["expired", "expired"]
        assert (_grant_state(ua, "grant-r3"), _grant_state(ua, "grant-r4")) == ("approved", "pending")   # 읽기는 상태를 바꾸지 않는다
        assert _code(lambda: webchat.grant_status(ub, "grant-r3")) == "NOT-FOUND"
        ok("grant: 만료(서버 now 기준) 뒤 승인·소비 모두 GRANT-EXPIRED · 상태 조회 = expired(읽기 전용, 남의 것 NOT-FOUND)")
    finally:
        webchat._desktop_verifier = None
        with db.tx() as c:
            c.execute("DELETE FROM chat_provider_grants WHERE user_id IN (%s,%s) AND request_id LIKE 'grant-%%'", (ua, ub))


def _wait_for_db_lock_wait(table_fragment):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        waiting = rows("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() "
                       "AND wait_event_type='Lock' AND query ILIKE %s", (f"%{table_fragment}%",))
        if waiting:
            return
        time.sleep(0.02)
    raise AssertionError(f"worker did not block on {table_fragment}")


def _wait_until_db_epoch(epoch):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        expired = rows("SELECT clock_timestamp() >= to_timestamp(%s) AS expired", (epoch,))[0]["expired"]
        if expired:
            return
        time.sleep(0.02)
    raise AssertionError("synthetic expiry did not pass")


def _wait_until_db_time(timestamp):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        expired = rows("SELECT clock_timestamp() >= %s AS expired", (timestamp,))[0]["expired"]
        if expired:
            return
        time.sleep(0.02)
    raise AssertionError("synthetic timestamp expiry did not pass")


def test_wall_clock_expiry_after_row_lock_wait(ua, dev_a):
    """grant expiry checks use wall clock after FOR UPDATE wait, not transaction-start now()."""
    old = webchat._desktop_verifier
    webchat._desktop_verifier = lambda *_: True
    try:
        for rid, operation, expected_state in (
            ("lock-approve", lambda: webchat.grant_approve(ua, "lock-approve", True), "pending"),
            ("lock-consume", lambda: _grant_consume(ua, dev_a, "claude", "test-model", "lock-consume"), "approved"),
        ):
            webchat.grant_request(ua, dev_a, "claude", "test-model", rid)
            with db.tx() as c:
                if rid == "lock-consume":
                    c.execute("UPDATE chat_provider_grants SET state='approved', approved_at=clock_timestamp() WHERE user_id=%s AND request_id=%s", (ua, rid))
                exp = c.execute("UPDATE chat_provider_grants SET expires_at=clock_timestamp()+interval '2 seconds' WHERE user_id=%s AND request_id=%s RETURNING expires_at",
                                (ua, rid)).fetchone()["expires_at"]
            result, error = {}, threading.Event()

            def worker():
                try:
                    operation()
                    result["ok"] = True
                except db.CrmError as e:
                    result["code"] = e.code
                except BaseException as e:
                    result["error"] = type(e).__name__
                finally:
                    error.set()

            with db.tx() as locker:
                locker.execute("SELECT id FROM chat_provider_grants WHERE user_id=%s AND request_id=%s FOR UPDATE", (ua, rid))
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                _wait_for_db_lock_wait("chat_provider_grants")
                _wait_until_db_time(exp)
            thread.join(timeout=3)
            assert not thread.is_alive() and error.is_set(), rid
            assert result.get("code") == "GRANT-EXPIRED", (rid, result)
            assert _grant_state(ua, rid) == expected_state, (rid, _grant_state(ua, rid))
        ok("grant 승인·소비: FOR UPDATE 대기 중 만료되면 wall clock 기준 GRANT-EXPIRED")
    finally:
        webchat._desktop_verifier = old
        with db.tx() as c:
            c.execute("DELETE FROM chat_provider_grants WHERE user_id=%s AND request_id IN ('lock-approve','lock-consume')", (ua,))


def test_consent_challenge(ua, ub, tok_a, dev_a):
    """PC 동의 키(PoP·회전·폐기)·challenge(바인딩·1회·만료·폐기) — 합성 키만. 운영 provider verifier 는 None 그대로."""
    import base64
    import secrets
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import consent_signature

    def spki(k):
        return k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    def sign(k, claims):
        return base64.urlsafe_b64encode(k.sign(consent_signature.encode_consent(claims))).rstrip(b"=").decode("ascii")

    def ch_state(nonce):
        return rows("SELECT state FROM chat_consent_challenges WHERE user_id=%s AND nonce=%s", (ua, nonce))[0]["state"]

    bearer = "Bearer " + tok_a
    inst, inst_x = "di_" + secrets.token_hex(12), "di_" + secrets.token_hex(12)
    other = imports.device_connect(ub, "b consent pc")
    k1, k2, k3 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    begin = webchat.consent_key_begin
    activate = webchat.consent_key_activate
    try:
        with db.tx() as c:
            c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'consent pc','darwin',%s)", (ua, inst, dev_a))
            c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'consent pc x','darwin',NULL)", (ua, inst_x))
        # 머리글 표식·빈 값·가짜 토큰은 증거가 아니다
        for auth in ("", None, "X-MyCRM-Desktop: 1", "Bearer not-a-token"):
            assert _code(lambda: begin(ua, auth, inst, spki(k1))) in ("AUTH-INVALID", "AUTH-BLOCKED"), auth
        assert _code(lambda: begin(ub, bearer, inst, spki(k1))) == "CONSENT_REQUIRED"                     # 세션 사용자 ≠ 토큰 사용자
        assert _code(lambda: begin(ua, "Bearer " + other["token"], inst, spki(k1))) == "CONSENT_REQUIRED"  # 남의 장치 토큰
        assert _code(lambda: begin(ua, bearer, inst_x, spki(k1))) == "CONSENT_REQUIRED"                   # 이 장치에 묶이지 않은 설치본
        assert _code(lambda: begin(ua, bearer, "di_bad", spki(k1))) == "ARG-INVALID"
        assert _code(lambda: begin(ua, bearer, inst, b"\x00" * 44)) == "ARG-INVALID"
        ok("동의 키: 세션 사용자·장치 Bearer 토큰·설치본 묶음이 모두 맞아야 시작(머리글 표식 무시)")

        b = begin(ua, bearer, inst, spki(k1))
        assert b["claims"]["provider"] == webchat.KEY_POP_PROVIDER and b["claims"]["device_id"] == dev_a and b["claims"]["session_id"] == b["key_id"]
        assert _code(lambda: activate(ua, bearer, inst, b["key_id"], sign(k2, b["claims"]))) == "CONSENT_REQUIRED"   # 다른 키 서명
        assert _code(lambda: activate(ua, bearer, inst, b["key_id"], sign(k1, b["claims"]))) == "CONSENT_REQUIRED"   # 시도는 한 번뿐
        b = begin(ua, bearer, inst, spki(k1))
        assert _code(lambda: activate(ub, bearer, inst, b["key_id"], sign(k1, b["claims"]))) == "CONSENT_REQUIRED"   # 다른 세션
        assert activate(ua, bearer, inst, b["key_id"], sign(k1, b["claims"]))["state"] == "active"
        b2 = begin(ua, bearer, inst, spki(k2))
        assert _code(lambda: activate(ua, bearer, inst, b2["key_id"], sign(k2, b2["claims"]))) == "CONSENT_REQUIRED"  # 옛 키 서명 없는 교체
        b2 = begin(ua, bearer, inst, spki(k2))
        assert _code(lambda: activate(ua, bearer, inst, b2["key_id"], sign(k2, b2["claims"]), sign(k3, dict(b2["claims"], model="rotate")))) == "CONSENT_REQUIRED"
        b2 = begin(ua, bearer, inst, spki(k2))
        out = activate(ua, bearer, inst, b2["key_id"], sign(k2, b2["claims"]), sign(k1, dict(b2["claims"], model="rotate")))
        assert out["state"] == "active" and out["rotated"], out
        act = rows("SELECT id FROM desktop_consent_keys WHERE user_id=%s AND installation_id=%s AND state='active'", (ua, inst))
        assert [r["id"] for r in act] == [b2["key_id"]], act
        ok("동의 키: 새 키 PoP 필수·1회 시도·회전은 옛 키 서명 필수·active 1개")

        webchat.grant_request(ua, dev_a, "claude", "test-model", "consent-r1")
        issue = webchat.consent_challenge_issue
        verify = webchat.consent_challenge_verify
        webchat.grant_request(ua, dev_a, "claude", "claude/opus+latest", "consent-r-model")
        model_ch = issue(ua, bearer, inst, "consent-r-model")
        model_claims = model_ch["claims"]
        assert model_claims["model"] == "claude/opus+latest"
        assert verify(ua, bearer, inst, model_claims["nonce"], sign(k2, model_claims))["state"] == "verified"
        assert _code(lambda: issue(ua, bearer, inst, "consent-none")) == "GRANT-INVALID"
        assert _code(lambda: issue(ub, bearer, inst, "consent-r1")) == "CONSENT_REQUIRED"
        assert _code(lambda: issue(ua, bearer, inst_x, "consent-r1")) == "CONSENT_REQUIRED"
        for field, val in (("provider", "codex"), ("model", "other-model"), ("session_id", "consent-r2"), ("device_id", "is_other"),
                           ("user_id", ub), ("nonce", "A" * 43), ("expires_at", None)):
            ch = issue(ua, bearer, inst, "consent-r1")
            cl = ch["claims"]
            assert (cl["user_id"], cl["device_id"], cl["session_id"], cl["provider"], cl["model"]) == (ua, dev_a, "consent-r1", "claude", "test-model"), cl
            bad = dict(cl, **{field: cl["expires_at"] + 1 if val is None else val})
            assert _code(lambda: verify(ua, bearer, inst, cl["nonce"], sign(k2, bad))) == "CONSENT_REQUIRED", field
            assert ch_state(cl["nonce"]) == "rejected", field
            assert (webchat.grant_status(ua, "consent-r1")["state"], webchat.grant_status(ua, "consent-r1")["prompt"]) == ("pending", "closed"), field
        ch = issue(ua, bearer, inst, "consent-r1")
        cl = ch["claims"]
        assert _code(lambda: verify(ua, bearer, inst, cl["nonce"], sign(k1, cl))) == "CONSENT_REQUIRED"   # 폐기된 옛 키
        ch = issue(ua, bearer, inst, "consent-r1")
        cl = ch["claims"]
        stale = issue(ua, bearer, inst, "consent-r1")   # 새 challenge 가 옛 것을 폐기
        assert ch_state(cl["nonce"]) == "revoked"
        assert _code(lambda: verify(ua, bearer, inst, cl["nonce"], sign(k2, cl))) == "GRANT-USED"
        cl = stale["claims"]
        assert _code(lambda: verify(ub, bearer, inst, cl["nonce"], sign(k2, cl))) == "CONSENT_REQUIRED"   # 다른 세션은 상태를 못 바꾼다
        assert _code(lambda: verify(ua, "Bearer " + other["token"], inst, cl["nonce"], sign(k2, cl))) == "CONSENT_REQUIRED"
        assert ch_state(cl["nonce"]) == "issued"
        out = verify(ua, bearer, inst, cl["nonce"], sign(k2, cl))
        assert out["state"] == "verified", out
        assert _code(lambda: verify(ua, bearer, inst, cl["nonce"], sign(k2, cl))) == "GRANT-USED"   # 재생
        assert _grant_state(ua, "consent-r1") == "approved" and webchat._desktop_verifier is None
        assert _code(lambda: webchat.grant_approve(ua, "consent-r1", out)) == "CONSENT_REQUIRED"   # 대체 verifier 경로는 계속 닫혀 있다
        ok("동의 challenge: 7필드 바인딩·DB 기준 재구성·1회 시도·재발급 시 옛 것 폐기·재생 GRANT-USED·signed approval")

        webchat.grant_request(ua, dev_a, "claude", "test-model", "consent-expiry")
        assert webchat.grant_status(ua, "consent-expiry")["prompt"] == "none"
        ch = issue(ua, bearer, inst, "consent-expiry")
        assert webchat.grant_status(ua, "consent-expiry")["prompt"] == "open"
        with db.tx() as c:
            c.execute("UPDATE chat_consent_challenges SET expires_at=floor(extract(epoch from now()))::bigint - 1 WHERE nonce=%s", (ch["claims"]["nonce"],))
        st = webchat.grant_status(ua, "consent-expiry")   # PC 창이 응답 없이 끝남(취소와 구분하지 않는다)
        assert (st["state"], st["prompt"]) == ("pending", "closed") and ch_state(ch["claims"]["nonce"]) == "issued", st
        cl = dict(ch["claims"], expires_at=rows("SELECT expires_at FROM chat_consent_challenges WHERE nonce=%s", (ch["claims"]["nonce"],))[0]["expires_at"])
        assert _code(lambda: verify(ua, bearer, inst, cl["nonce"], sign(k2, cl))) == "GRANT-EXPIRED"
        assert ch_state(cl["nonce"]) == "expired"

        # grant 만료가 grant 행 잠금 대기 중 지나면 challenge 를 발급하지 않는다.
        webchat.grant_request(ua, dev_a, "claude", "test-model", "consent-lock-issue")
        with db.tx() as c:
            exp = c.execute("UPDATE chat_provider_grants SET expires_at=clock_timestamp()+interval '2 seconds' "
                            "WHERE user_id=%s AND request_id='consent-lock-issue' "
                            "RETURNING floor(extract(epoch from expires_at))::bigint AS exp", (ua,)).fetchone()["exp"]
        result, finished = {}, threading.Event()

        def issue_worker():
            try:
                result["value"] = issue(ua, bearer, inst, "consent-lock-issue")
            except db.CrmError as e:
                result["code"] = e.code
            except BaseException as e:
                result["error"] = type(e).__name__
            finally:
                finished.set()

        with db.tx() as locker:
            locker.execute("SELECT id FROM chat_provider_grants WHERE user_id=%s AND request_id='consent-lock-issue' FOR UPDATE", (ua,))
            thread = threading.Thread(target=issue_worker, daemon=True)
            thread.start()
            _wait_for_db_lock_wait("chat_provider_grants")
            _wait_until_db_epoch(exp)
        thread.join(timeout=3)
        assert not thread.is_alive() and finished.is_set()
        assert result.get("code") == "GRANT-EXPIRED", result
        assert rows("SELECT count(*) AS n FROM chat_consent_challenges WHERE user_id=%s AND session_id='consent-lock-issue'", (ua,))[0]["n"] == 0

        # challenge 검증도 row 잠금 대기 뒤 만료된 서명을 통과시키지 않는다.
        webchat.grant_request(ua, dev_a, "claude", "test-model", "consent-lock-verify")
        ch = issue(ua, bearer, inst, "consent-lock-verify")
        with db.tx() as c:
            exp = c.execute("UPDATE chat_consent_challenges SET expires_at=floor(extract(epoch from clock_timestamp()))::bigint + 2 "
                            "WHERE nonce=%s RETURNING expires_at", (ch["claims"]["nonce"],)).fetchone()["expires_at"]
        cl = dict(ch["claims"], expires_at=exp)
        signature = sign(k2, cl)
        result, finished = {}, threading.Event()

        def verify_worker():
            try:
                result["value"] = verify(ua, bearer, inst, cl["nonce"], signature)
            except db.CrmError as e:
                result["code"] = e.code
            except BaseException as e:
                result["error"] = type(e).__name__
            finally:
                finished.set()

        with db.tx() as locker:
            locker.execute("SELECT id FROM chat_consent_challenges WHERE user_id=%s AND nonce=%s FOR UPDATE", (ua, cl["nonce"]))
            thread = threading.Thread(target=verify_worker, daemon=True)
            thread.start()
            _wait_for_db_lock_wait("chat_consent_challenges")
            _wait_until_db_epoch(exp)
        thread.join(timeout=3)
        assert not thread.is_alive() and finished.is_set()
        assert result.get("code") == "GRANT-EXPIRED", result
        assert ch_state(cl["nonce"]) == "expired"
        ok("challenge 발급·검증: FOR UPDATE 대기 중 만료되면 wall clock 기준 fail-closed")
        webchat.grant_request(ua, dev_a, "claude", "test-model", "consent-revoke")
        ch = issue(ua, bearer, inst, "consent-revoke")
        assert webchat.consent_key_revoke(ua, inst) == 1
        assert ch_state(ch["claims"]["nonce"]) == "revoked"
        assert _code(lambda: verify(ua, bearer, inst, ch["claims"]["nonce"], sign(k2, ch["claims"]))) == "GRANT-USED"
        assert _code(lambda: issue(ua, bearer, inst, "consent-revoke")) == "CONSENT_REQUIRED"   # active 키 없음
        rebound = begin(ua, bearer, inst, spki(k2))
        rebound_result = activate(ua, bearer, inst, rebound["key_id"], sign(k2, rebound["claims"]))
        assert rebound_result == {"key_id": rebound["key_id"], "state": "active", "rotated": False}, rebound_result
        webchat.grant_request(ua, dev_a, "claude", "test-model", "consent-after-lock")
        fresh = issue(ua, bearer, inst, "consent-after-lock")["claims"]
        assert verify(ua, bearer, inst, fresh["nonce"], sign(k2, fresh))["state"] == "verified"
        ok("화면 잠금 뒤 키 폐기: 같은 OS 보호 키를 새 PoP로 재등록하고 새 세션 challenge 승인 가능")
        ok("동의 challenge: 만료 expired·키 폐기 시 issued challenge 함께 폐기·키 없으면 발급 거절")
    finally:
        with db.tx() as c:
            c.execute("DELETE FROM chat_consent_challenges WHERE user_id=%s", (ua,))
            c.execute("DELETE FROM chat_provider_permits WHERE user_id=%s", (ua,))
            c.execute("DELETE FROM desktop_consent_keys WHERE user_id=%s", (ua,))
            c.execute("DELETE FROM desktop_installations WHERE user_id=%s AND id IN (%s,%s)", (ua, inst, inst_x))
            c.execute("DELETE FROM chat_provider_grants WHERE user_id=%s AND request_id LIKE 'consent-%%'", (ua,))
        imports.device_revoke(ub, other["device"]["id"])


def test_consent_result(srv, ua, ub, tok_a, dev_a):
    """F9(2026-11-11): PC 앱이 동의 창이 허용 없이 끝났다고 장치 WS consent.result 로 알린다. 그 사용자, 장치의 pending grant 만
    처음 한 번 닫고(멱등, 응답 없음) issued challenge 를 revoked 로 바꾼다. 닫힌 grant 는 challenge 발급, 서명 검증, 소비가 거절되고
    상태 prompt 는 declined(거절) 또는 closed(locked, failed)다. 합성 키, 합성 설치본만."""
    import base64
    import secrets
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import consent_signature

    def spki(k):
        return k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    def sign(k, claims):
        return base64.urlsafe_b64encode(k.sign(consent_signature.encode_consent(claims))).rstrip(b"=").decode("ascii")

    def ch_state(nonce):
        return rows("SELECT state FROM chat_consent_challenges WHERE user_id=%s AND nonce=%s", (ua, nonce))[0]["state"]

    def reason(rid):
        return rows("SELECT close_reason FROM chat_provider_grants WHERE user_id=%s AND request_id=%s", (ua, rid))[0]["close_reason"]

    def wait_reason(rid, want, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if reason(rid) == want:
                return True
            time.sleep(0.05)
        return reason(rid) == want

    bearer = "Bearer " + tok_a
    inst = "di_" + secrets.token_hex(12)
    other = imports.device_connect(ua, "a consent-result other pc")
    key = Ed25519PrivateKey.generate()
    issue, verify = webchat.consent_challenge_issue, webchat.consent_challenge_verify
    pc = None
    try:
        with db.tx() as c:
            c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'cr pc','darwin',%s)",
                      (ua, inst, dev_a))
        b = webchat.consent_key_begin(ua, bearer, inst, spki(key))
        assert webchat.consent_key_activate(ua, bearer, inst, b["key_id"], sign(key, b["claims"]))["state"] == "active"

        webchat.grant_request(ua, dev_a, "claude", "test-model", "cr-declined")
        ch = issue(ua, bearer, inst, "cr-declined")["claims"]
        assert webchat.grant_status(ua, "cr-declined")["prompt"] == "open"
        pc = PC(srv, tok_a)
        pc.send({"type": "consent.result", "request_id": "cr-declined", "outcome": "declined"})
        assert wait_reason("cr-declined", "declined"), reason("cr-declined")
        assert ch_state(ch["nonce"]) == "revoked"
        st = webchat.grant_status(ua, "cr-declined")
        assert (st["state"], st["prompt"], st["close_reason"]) == ("pending", "declined", "declined"), st
        assert pc.wait(lambda m: m.get("type") != "ping", 0.3) is None   # 응답을 보내지 않는다
        pc.send({"type": "consent.result", "request_id": "cr-declined", "outcome": "locked"})   # 이미 닫힘 = 그대로
        pc.send({"type": "consent.result", "request_id": "cr-declined", "outcome": ["declined"]})   # 형식 틀림 = 무시
        time.sleep(0.3)
        assert reason("cr-declined") == "declined" and pc.closed is None
        ok("consent.result: WS 로 받은 거절이 그 grant 를 declined 로 닫고 issued challenge 를 revoked(응답 없음, 두 번째는 그대로)")

        assert _code(lambda: issue(ua, bearer, inst, "cr-declined")) == "GRANT-INVALID"
        assert _code(lambda: verify(ua, bearer, inst, ch["nonce"], sign(key, ch))) == "GRANT-USED"
        assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "cr-declined")) == "CONSENT_REQUIRED"
        assert _grant_state(ua, "cr-declined") == "pending"
        # 서명 검증: challenge 가 아직 issued 여도 grant 가 닫혔으면 승인하지 않는다(revoked 로 끝낸다)
        webchat.grant_request(ua, dev_a, "claude", "test-model", "cr-verify")
        cv = issue(ua, bearer, inst, "cr-verify")["claims"]
        with db.tx() as c:
            c.execute("UPDATE chat_provider_grants SET close_reason='failed' WHERE user_id=%s AND request_id='cr-verify'", (ua,))
        assert _code(lambda: verify(ua, bearer, inst, cv["nonce"], sign(key, cv))) == "CONSENT_REQUIRED"
        assert ch_state(cv["nonce"]) == "revoked" and _grant_state(ua, "cr-verify") == "pending"
        st = webchat.grant_status(ua, "cr-verify")
        assert (st["prompt"], st["close_reason"]) == ("closed", "failed"), st   # J-F2: 화면이 실패와 거절을 나눈다
        # 소비: 승인된 grant 에 이유가 붙어 있으면(직접 넣은 합성 상태) 소비하지 않는다
        webchat.grant_request(ua, dev_a, "claude", "test-model", "cr-consume")
        cc = issue(ua, bearer, inst, "cr-consume")["claims"]
        assert verify(ua, bearer, inst, cc["nonce"], sign(key, cc))["state"] == "verified"
        with db.tx() as c:
            c.execute("UPDATE chat_provider_grants SET close_reason='failed' WHERE user_id=%s AND request_id='cr-consume'", (ua,))
        assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "cr-consume")) == "CONSENT_REQUIRED"
        assert _grant_state(ua, "cr-consume") == "approved"
        ok("닫힌 grant: challenge 발급 GRANT-INVALID, 서명 검증 거절(revoked), 소비 CONSENT_REQUIRED")

        me = {"user_id": ua, "id": dev_a}
        webchat.grant_request(ua, dev_a, "claude", "test-model", "cr-locked")
        assert webchat.consent_result(me, "cr-locked", "locked") is True
        st = webchat.grant_status(ua, "cr-locked")
        assert (st["prompt"], st["close_reason"]) == ("closed", "locked"), st
        webchat.grant_request(ua, dev_a, "claude", "test-model", "cr-other")
        assert webchat.consent_result({"user_id": ua, "id": other["device"]["id"]}, "cr-other", "declined") is False   # 다른 장치
        assert webchat.consent_result({"user_id": ub, "id": dev_a}, "cr-other", "declined") is False                    # 다른 사용자
        for bad_rid, bad_outcome in (("cr-other", "cancelled"), ("cr-other", None), ("bad id!", "declined"), (None, "declined"),
                                     ("cr-none", "declined")):
            assert webchat.consent_result(me, bad_rid, bad_outcome) is False, (bad_rid, bad_outcome)
        assert reason("cr-other") is None and webchat.grant_status(ua, "cr-other")["prompt"] == "none"
        assert webchat.consent_result(me, "cr-consume", "declined") is False   # 이미 approved
        assert reason("cr-consume") == "failed"
        ok("consent.result: locked 는 closed, 다른 장치, 다른 사용자, 목록 밖, 없음, 승인된 grant 는 바꾸지 않는다")

        h = web(srv, ua)
        body = {"device_id": dev_a, "provider": "claude", "model": "test-model"}
        r = h.post("/api/chat/grants", json={**body, "request_id": "cr-declined"})
        assert r.status_code == 200 and r.json()["state"] == "pending", r.text
        assert pc.wait(lambda m: m.get("type") == "consent.request", 0.5) is None   # 닫힌 grant 에 창을 다시 띄우지 않는다
        r = h.post("/api/chat/grants", json={**body, "request_id": "cr-fresh"})
        assert r.status_code == 201, r.text
        m = pc.wait(lambda m: m.get("type") == "consent.request", 3)
        assert m and m["request_id"] == "cr-fresh", m
        st = h.get("/api/chat/grants/cr-declined").json()
        assert st["prompt"] == "declined", st
        ok("grant 요청 route: 닫힌 같은 요청은 PC 에 consent.request 를 다시 보내지 않고, 새 요청은 보낸다. GET prompt=declined")
    finally:
        if pc:
            pc.close()
        with db.tx() as c:
            c.execute("DELETE FROM chat_consent_challenges WHERE user_id=%s AND installation_id=%s", (ua, inst))
            c.execute("DELETE FROM desktop_consent_keys WHERE user_id=%s AND installation_id=%s", (ua, inst))
            c.execute("DELETE FROM desktop_installations WHERE user_id=%s AND id=%s", (ua, inst))
            c.execute("DELETE FROM chat_provider_grants WHERE user_id=%s AND request_id LIKE 'cr-%%'", (ua,))
        imports.device_revoke(ua, other["device"]["id"])


def test_consent_routes(srv, ua, ub, tok_a, dev_a):
    """HTTP route: grant 요청·동의 키·challenge. 권한 = 웹 세션 uid 뿐, Origin 은 CSRF 방어뿐(PC 증거 아님), 키·challenge 는 Bearer 필수.
    합성 키·합성 설치본만. verified 서명 grant 는 session_new 에서 한 번 소비해 세션을 만들며, provider turn 은 계속 fail-closed."""
    import base64
    import secrets
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import consent_signature

    def b64(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def spki(k):
        return b64(k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))

    def sign(k, claims):
        return b64(k.sign(consent_signature.encode_consent(claims)))

    def ch_state(nonce):
        return rows("SELECT state FROM chat_consent_challenges WHERE user_id=%s AND nonce=%s", (ua, nonce))[0]["state"]

    def n_keys(state=None):
        if state:
            return rows("SELECT count(*) AS n FROM desktop_consent_keys WHERE user_id=%s AND state=%s", (ua, state))[0]["n"]
        return rows("SELECT count(*) AS n FROM desktop_consent_keys WHERE user_id=%s", (ua,))[0]["n"]

    def n_grants(rid):
        return rows("SELECT count(*) AS n FROM chat_provider_grants WHERE user_id=%s AND request_id=%s", (ua, rid))[0]["n"]

    def post(h, path, body=None, auth=None, headers=None, raw=None):
        hd = dict(headers or {})
        if auth is not None:
            hd["authorization"] = auth
        if raw is not None:
            hd.setdefault("content-type", "application/json")
            return h.post(path, content=raw, headers=hd)
        return h.post(path, json=body, headers=hd)

    def code(r, status, c):
        assert r.status_code == status and r.json()["code"] == c, (status, c, r.status_code, r.text)
        assert r.headers.get("cache-control") == "no-store"

    GRANT, BEGIN, ACT, REV = "/api/chat/grants", "/api/chat/consent/keys/begin", "/api/chat/consent/keys/activate", "/api/chat/consent/keys/revoke"
    ISSUE, VERIFY = "/api/chat/consent/challenges/issue", "/api/chat/consent/challenges/verify"
    bearer = "Bearer " + tok_a
    inst, inst_x, inst_2 = ("di_" + secrets.token_hex(12) for _ in range(3))
    gateway_inst = None
    gateway_device = None
    mcp_session = None
    dispatch_turn = None
    created_session = None
    previous_id = None
    other = imports.device_connect(ub, "b consent route pc")
    a2 = imports.device_connect(ua, "a consent route pc2")
    foreign, bearer_a2 = "Bearer " + other["token"], "Bearer " + a2["token"]
    pc = PC(srv, tok_a, capabilities=[{"provider": "fake", "models": [None, "fake-test"]},
                                     {"provider": "claude", "models": ["test-model"]}])
    k1, k2 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    grant_body = {"device_id": dev_a, "provider": "claude", "model": "test-model", "request_id": "route-r1"}
    begin_body = {"installation_id": inst, "spki": spki(k1)}
    shaped = ((GRANT, grant_body, None), (BEGIN, begin_body, bearer),
              (ACT, {"installation_id": inst, "key_id": "ck_" + "0" * 24, "pop_signature": "A" * 86}, bearer),
              (REV, {"installation_id": inst}, bearer), (ISSUE, {"installation_id": inst, "request_id": "route-r1"}, bearer),
              (VERIFY, {"installation_id": inst, "nonce": "A" * 43, "signature": "A" * 86}, bearer))
    try:
        with db.tx() as c:
            for i, d in ((inst, dev_a), (inst_x, None), (inst_2, a2["device"]["id"])):
                c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'consent route pc','darwin',%s)", (ua, i, d))

        # 세션 없음 401(유효 Bearer·표식이 있어도) · Origin 다름·없음 403(표식은 증거가 아니다)
        with web(srv) as h:
            for path, body, auth in shaped:
                code(post(h, path, body, auth, headers={"x-mycrm-desktop": "1"}), 401, "UNAUTHORIZED")
        with web(srv, ua, origin=False) as h:
            for path, body, auth in shaped:
                code(post(h, path, body, auth, headers={"origin": "https://evil.example"}), 403, "ORIGIN")
                code(post(h, path, body, auth, headers={"x-mycrm-desktop": "1"}), 403, "ORIGIN")
        assert n_grants("route-r1") == 0 and n_keys() == 0
        ok("동의 route: 세션 없음 401 · 다른/없는 Origin 403(X-MyCRM-Desktop 표식 무시) · 상태 변화 없음")

        with web(srv, ua) as h:
            # Bearer 없음·형식 틀림·여러 개·가짜 = 401 AUTH-INVALID (grant 요청 route 는 Bearer 를 쓰지 않는다)
            for path, body, _ in shaped[1:]:
                for auth in (None, "Basic abc", "X-MyCRM-Desktop: 1", "Bearer not-a-token", "Bearer " + "x" * 600):
                    code(post(h, path, body, auth), 401, "AUTH-INVALID")
                code(post(h, path, body, headers={"x-mycrm-desktop": "1"}), 401, "AUTH-INVALID")
                code(h.post(path, json=body, headers=[("authorization", bearer), ("authorization", bearer)]), 401, "AUTH-INVALID")
            # 남의 토큰·묶이지 않은 설치본·다른 장치 설치본 = 409 CONSENT_REQUIRED. 본문의 user_id·device_id 는 받지 않는다
            code(post(h, BEGIN, begin_body, foreign), 409, "CONSENT_REQUIRED")
            code(post(h, BEGIN, begin_body, bearer_a2), 409, "CONSENT_REQUIRED")
            code(post(h, BEGIN, dict(begin_body, installation_id=inst_x), bearer), 409, "CONSENT_REQUIRED")
            code(post(h, BEGIN, dict(begin_body, installation_id=inst_2), bearer), 409, "CONSENT_REQUIRED")
            code(post(h, BEGIN, dict(begin_body, user_id=ub), bearer), 400, "ARG-INVALID")
            code(post(h, BEGIN, dict(begin_body, device_id=a2["device"]["id"]), bearer), 400, "ARG-INVALID")
            # 본문 모양·크기
            for raw in (b"not json", b"[]", b'"x"', b"{}", b"\xff\xfe", b"[" * 1500 + b"]" * 1500,
                        json.dumps({"installation_id": inst, "spki": begin_body["spki"]}).replace("}", ', "installation_id": "%s"}' % inst).encode(),
                        ('{"installation_id": NaN, "spki": "%s"}' % begin_body["spki"]).encode()):
                code(post(h, BEGIN, auth=bearer, raw=raw), 400, "ARG-INVALID")
            for body in ({"installation_id": inst}, {"installation_id": 1, "spki": begin_body["spki"]}, dict(begin_body, spki=None),
                         dict(begin_body, spki=begin_body["spki"] + "="), dict(begin_body, spki=b64(b"\x00" * 44)),
                         dict(begin_body, spki=""), dict(begin_body, installation_id="di_bad")):
                code(post(h, BEGIN, body, bearer), 400, "ARG-INVALID")
            code(post(h, BEGIN, auth=bearer, raw=json.dumps(begin_body).encode(), headers={"content-type": "text/plain"}), 400, "ARG-INVALID")
            code(post(h, BEGIN, auth=bearer, raw=json.dumps(dict(begin_body, pad="x" * 5000)).encode()), 413, "TEXT-LIMIT")
            assert n_keys() == 0
            ok("동의 route: Bearer 없음·형식·중복·가짜 401 · 남의 토큰·설치본·장치 불일치 409 · 본문 권한 필드·모양·4KB 초과 거절 · 키 미생성")

            # grant 요청 route — 세션 uid 의 장치만, 멱등·충돌, 상태 필드 못 넣음
            r = post(h, GRANT, grant_body)
            assert r.status_code == 201 and r.headers.get("cache-control") == "no-store", r.text
            g = r.json()
            assert (g["request_id"], g["device_id"], g["provider"], g["model"], g["state"], g["created"]) == ("route-r1", dev_a, "claude", "test-model", "pending", True), g
            assert "user_id" not in g
            notice = pc.wait(lambda m: m.get("type") == "consent.request", timeout=2)
            assert notice == {"type": "consent.request", "request_id": "route-r1"}, notice
            r = post(h, GRANT, grant_body)
            assert r.status_code == 200 and r.json()["created"] is False, r.text
            code(post(h, GRANT, dict(grant_body, provider="codex")), 409, "GRANT-CONFLICT")
            code(post(h, GRANT, dict(grant_body, request_id="route-rb", device_id=other["device"]["id"])), 404, "NOT-FOUND")
            code(post(h, GRANT, dict(grant_body, request_id="route-rf", provider="fake")), 400, "ARG-INVALID")
            code(post(h, GRANT, dict(grant_body, request_id="route-ru", user_id=ub)), 400, "ARG-INVALID")
            code(post(h, GRANT, dict(grant_body, request_id="route-rs", state="approved")), 400, "ARG-INVALID")
            code(post(h, GRANT, {k: v for k, v in grant_body.items() if k != "model"}), 400, "ARG-INVALID")
            assert _grant_state(ua, "route-r1") == "pending" and n_grants("route-rb") + n_grants("route-ru") + n_grants("route-rs") == 0
            st = h.get("/api/chat/grants/route-r1")
            assert st.status_code == 200 and st.headers.get("cache-control") == "no-store", st.text
            assert st.json() == {"request_id": "route-r1", "device_id": dev_a, "provider": "claude", "model": "test-model", "state": "pending",
                                 "prompt": "none", "close_reason": None, "expires_at": g["expires_at"], "connected": True}, st.json()
            r = h.get("/api/chat/grants/route-none")
            assert r.status_code == 404 and r.json()["code"] == "NOT-FOUND", r.text
            r = h.get("/api/chat/grants/bad%20id!")
            assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", r.text
            assert _grant_state(ua, "route-r1") == "pending"
            ok("grant route: 세션 uid 의 활성 장치만 · 201/200 멱등 · GRANT-CONFLICT · 남의 장치 404 · user_id·state 필드 거절 · pending")

            # 키 등록 — 새 키 PoP, 1회 시도, 남의 토큰은 상태를 못 바꾼다
            r = post(h, BEGIN, begin_body, bearer)
            assert r.status_code == 200, r.text
            b = r.json()
            assert (b["claims"]["user_id"], b["claims"]["device_id"], b["claims"]["session_id"]) == (ua, dev_a, b["key_id"]), b
            act = {"installation_id": inst, "key_id": b["key_id"], "pop_signature": sign(k2, b["claims"])}
            code(post(h, ACT, act, bearer), 409, "CONSENT_REQUIRED")                                  # 다른 키 서명
            code(post(h, ACT, dict(act, pop_signature=sign(k1, b["claims"])), bearer), 409, "CONSENT_REQUIRED")   # 시도는 한 번뿐
            b = post(h, BEGIN, begin_body, bearer).json()
            act = {"installation_id": inst, "key_id": b["key_id"], "pop_signature": sign(k1, b["claims"])}
            code(post(h, ACT, act, foreign), 409, "CONSENT_REQUIRED")
            code(post(h, ACT, dict(act, device_id=dev_a), bearer), 400, "ARG-INVALID")
            assert n_keys("pending") == 1
            r = post(h, ACT, act, bearer)
            assert r.status_code == 200 and r.json() == {"key_id": b["key_id"], "state": "active", "rotated": False}, r.text
            ok("동의 키 route: begin→activate PoP · 1회 시도 · 남의 토큰은 pending 키를 못 건드림 · active")

            # challenge 발급 — 남의 토큰·설치본·장치 불일치 거절
            iss = {"installation_id": inst, "request_id": "route-r1"}
            for auth, body in ((foreign, iss), (bearer_a2, iss), (bearer, dict(iss, installation_id=inst_x)), (bearer, dict(iss, installation_id=inst_2))):
                code(post(h, ISSUE, body, auth), 409, "CONSENT_REQUIRED")
            code(post(h, ISSUE, dict(iss, request_id="route-none"), bearer), 409, "GRANT-INVALID")
            r = post(h, ISSUE, iss, bearer)
            assert r.status_code == 200, r.text
            cl = r.json()["claims"]
            assert (cl["user_id"], cl["device_id"], cl["session_id"], cl["provider"], cl["model"]) == (ua, dev_a, "route-r1", "claude", "test-model"), cl
            st = h.get("/api/chat/grants/route-r1").json()
            assert (st["state"], st["prompt"]) == ("pending", "open") and cl["nonce"] not in json.dumps(st), st
            ver = {"installation_id": inst, "nonce": cl["nonce"], "signature": sign(k1, cl)}
            code(post(h, VERIFY, ver, foreign), 409, "CONSENT_REQUIRED")
            code(post(h, VERIFY, dict(ver, user_id=ua), bearer), 400, "ARG-INVALID")
            assert ch_state(cl["nonce"]) == "issued"
        with web(srv, ub) as hb:   # 다른 세션 + 이 PC 토큰 = 세션 uid ≠ 토큰 주인
            r = hb.get("/api/chat/grants/route-r1")   # 남의 허용 요청 = 없는 것과 같은 404
            assert r.status_code == 404 and r.json()["code"] == "NOT-FOUND" and dev_a not in r.text, r.text
            code(post(hb, VERIFY, ver, bearer), 409, "CONSENT_REQUIRED")
            code(post(hb, REV, {"installation_id": inst}, bearer), 409, "CONSENT_REQUIRED")
        assert ch_state(cl["nonce"]) == "issued" and n_keys("active") == 1

        with web(srv, ua) as h:
            r = post(h, VERIFY, ver, bearer)
            assert r.status_code == 200 and r.json()["state"] == "verified", r.text
            code(post(h, VERIFY, ver, bearer), 409, "GRANT-USED")   # 재생
            st = h.get("/api/chat/grants/route-r1").json()
            assert (st["state"], st["prompt"]) == ("approved", "done"), st
            # native 서명 검증은 grant 를 승인하지만 소비·provider 실행은 닫혀 있다
            assert _grant_state(ua, "route-r1") == "approved" and webchat._desktop_verifier is None
            assert _code(lambda: webchat.grant_approve(ua, "route-r1", r.json())) == "CONSENT_REQUIRED"
            # 승인 전후 binding mismatch는 이전 active 세션을 닫지 않는다.
            previous_id = webchat._id("cs")
            with db.tx() as c:
                c.execute("INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version) "
                          "VALUES (%s,%s,%s,'fake',NULL,'route-keep-active',2)", (previous_id, ua, dev_a))
            for uid, did, prov, mdl, expected in ((ub, dev_a, "claude", "test-model", "NOT-FOUND"),
                                                   (ua, a2["device"]["id"], "claude", "test-model", "GRANT-INVALID"),
                                                   (ua, dev_a, "claude", "other-model", "GRANT-INVALID")):
                assert _code(lambda: webchat.session_new(uid, did, prov, mdl, "route-r1", capability_ok=True)) == expected
            assert rows("SELECT status FROM chat_sessions WHERE id=%s", (previous_id,))[0]["status"] == "active"
            assert _grant_state(ua, "route-r1") == "approved"

            barrier=threading.Barrier(2); created=[]; failures=[]
            def create_session():
                try:
                    barrier.wait(timeout=3)
                    created.append(webchat.session_new(ua, dev_a, "claude", "test-model", "route-r1", capability_ok=True))
                except db.CrmError as e:
                    failures.append(e.code)
                except BaseException as e:
                    failures.append(type(e).__name__)
            threads=[threading.Thread(target=create_session,daemon=True) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join(timeout=5)
            assert all(not t.is_alive() for t in threads) and not failures and len(created)==2, (failures,created)
            sessions=[x[0] for x in created]
            assert sessions[0]["session_id"]==sessions[1]["session_id"]
            assert sorted(x[2] for x in created)==[False,True]
            assert rows("SELECT status FROM chat_sessions WHERE id=%s", (previous_id,))[0]["status"] == "closed"
            assert _grant_state(ua, "route-r1") == "consumed"
            assert h.get("/api/chat/grants/route-r1").json()["state"] == "consumed"
            assert _code(lambda: _grant_consume(ua, dev_a, "claude", "test-model", "route-r1")) == "GRANT-USED"
            created_session=sessions[0]["session_id"]
            # The HTTP route is still hard-off. Exercise the internal handler
            # directly with the already authenticated synthetic device and a
            # consumed grant so DB scope validation + guarded dispatch can be
            # tested without enabling a provider or external route.
            mcp_body = {"tool": "read", "op": "state_get", "params": {}}
            disabled = h.post("/api/chat/mcp", json=mcp_body, headers={"Authorization": bearer})
            assert disabled.status_code == 503 and bearer.encode() not in disabled.content
            new_turn = webchat.turn_create(ua, created_session, "synthetic signed turn", "route-turn-valid",
                                           connected=lambda _d: True, capable=lambda _s: True)
            assert new_turn["created"] and new_turn["session"]["id"] == created_session
            valid_turn_id = new_turn["turn"]["id"]
            webchat.turn_fail(valid_turn_id, "TEST-CLEANUP")

            def denied_turn(client_id):
                return _code(lambda: webchat.turn_create(ua, created_session, "must be denied", client_id,
                                                          connected=lambda _d: True, capable=lambda _s: True))

            grant_row = rows("SELECT id,created_at,approved_at,consumed_at,expires_at FROM chat_provider_grants "
                              "WHERE user_id=%s AND request_id='route-r1'", (ua,))[0]
            challenge_row = rows("SELECT id,key_id,installation_id,expires_at FROM chat_consent_challenges "
                                  "WHERE user_id=%s AND grant_id=%s AND state='verified'", (ua, grant_row["id"]))[0]
            key_row = rows("SELECT state,revoked_at FROM desktop_consent_keys WHERE id=%s", (challenge_row["key_id"],))[0]
            session_row = rows("SELECT client_session_id,provider,model,created_at,status FROM chat_sessions WHERE id=%s",
                               (created_session,))[0]
            # 대화 하나로 J(JD1): 세션 동의는 그 세션의 grant 가 아니라 (장치, 공급자) 서 있는 허용 행이 정한다.
            # grant 의 대기 TTL, 소비 상태, 30일 정리는 세션에 닿지 않는다
            permit_row = rows("SELECT * FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider='claude'", (ua, dev_a))[0]
            assert rows("SELECT permit_id FROM chat_sessions WHERE id=%s", (created_session,))[0]["permit_id"] == permit_row["id"]
            assert (permit_row["grant_id"], permit_row["challenge_id"], permit_row["key_id"], permit_row["installation_id"]) == (
                grant_row["id"], challenge_row["id"], challenge_row["key_id"], challenge_row["installation_id"]), permit_row
            with db.tx() as c:
                c.execute("UPDATE chat_provider_grants SET created_at=clock_timestamp()-interval '20 minutes', "
                          "approved_at=clock_timestamp()-interval '19 minutes', "
                          "consumed_at=clock_timestamp()-interval '1 second', "
                          "expires_at=clock_timestamp()-interval '2 seconds' WHERE id=%s", (grant_row["id"],))
            still_consented = webchat.turn_create(ua, created_session, "after grant expiry", "route-turn-after-expiry",
                                                   connected=lambda _d: True, capable=lambda _s: True)
            assert still_consented["created"]
            webchat.turn_fail(still_consented["turn"]["id"], "TEST-CLEANUP")
            with db.tx() as c:
                c.execute("UPDATE chat_provider_grants SET created_at=%s,approved_at=%s,consumed_at=%s,expires_at=%s WHERE id=%s",
                          (grant_row["created_at"], grant_row["approved_at"], grant_row["consumed_at"], grant_row["expires_at"], grant_row["id"]))

            def restore_permit():
                with db.tx() as c:
                    c.execute("DELETE FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider='claude'", (ua, dev_a))
                    c.execute("INSERT INTO chat_provider_permits (id,user_id,device_id,provider,installation_id,key_id,grant_id,challenge_id,created_at) "
                              "VALUES (%(id)s,%(user_id)s,%(device_id)s,%(provider)s,%(installation_id)s,%(key_id)s,%(grant_id)s,%(challenge_id)s,%(created_at)s)",
                              permit_row)

            with db.tx() as c:
                c.execute("DELETE FROM chat_provider_permits WHERE id=%s", (permit_row["id"],))
            assert denied_turn("route-turn-permit-gone") == "CONSENT_REQUIRED"
            restore_permit()
            with db.tx() as c:   # 다시 세운 허용(새 id)은 옛 허용에 묶인 세션을 살리지 않는다
                c.execute("UPDATE chat_provider_permits SET id=%s WHERE id=%s", (webchat._id("cp"), permit_row["id"]))
            assert denied_turn("route-turn-permit-replaced") == "CONSENT_REQUIRED"
            restore_permit()
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET permit_id=NULL WHERE id=%s", (created_session,))
            assert denied_turn("route-turn-no-permit-id") == "CONSENT_REQUIRED"   # J 이전 세션 = 닫힌 실패
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET permit_id=%s WHERE id=%s", (permit_row["id"], created_session))

            with db.tx() as c:
                c.execute("UPDATE desktop_consent_keys SET state='revoked',revoked_at=clock_timestamp() WHERE id=%s",
                          (challenge_row["key_id"],))
            assert denied_turn("route-turn-key-revoked") == "CONSENT_REQUIRED"
            with db.tx() as c:
                c.execute("UPDATE desktop_consent_keys SET state=%s,revoked_at=%s WHERE id=%s",
                          (key_row["state"], key_row["revoked_at"], challenge_row["key_id"]))

            with db.tx() as c:
                c.execute("UPDATE desktop_installations SET revoked_at=clock_timestamp() WHERE id=%s", (challenge_row["installation_id"],))
            assert denied_turn("route-turn-install-revoked") == "CONSENT_REQUIRED"
            with db.tx() as c:
                c.execute("UPDATE desktop_installations SET revoked_at=NULL WHERE id=%s", (challenge_row["installation_id"],))

            with db.tx() as c:   # 허용은 공급자 단위 — 세션의 공급자가 허용과 다르면 닫힌 실패
                c.execute("UPDATE chat_sessions SET provider='codex' WHERE id=%s", (created_session,))
            assert denied_turn("route-turn-provider-mismatch") == "CONSENT_REQUIRED"
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET provider=%s WHERE id=%s", (session_row["provider"], created_session))
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET created_at=clock_timestamp()-interval '31 days' WHERE id=%s",
                          (created_session,))
            assert denied_turn("route-turn-session-expired") == "CONSENT_REQUIRED"
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET created_at=%s WHERE id=%s",
                          (session_row["created_at"], created_session))

            original_device = rows("SELECT revoked_at,token_revoked_at,token_expires_at FROM import_streams WHERE id=%s", (dev_a,))[0]
            with db.tx() as c:
                c.execute("UPDATE import_streams SET token_revoked_at=clock_timestamp() WHERE id=%s", (dev_a,))
            assert denied_turn("route-turn-device-revoked") == "DEVICE-GONE"
            with db.tx() as c:
                c.execute("UPDATE import_streams SET revoked_at=%s,token_revoked_at=%s WHERE id=%s",
                          (original_device["revoked_at"], original_device["token_revoked_at"], dev_a))
                c.execute("UPDATE chat_sessions SET status=%s WHERE id=%s", (session_row["status"], created_session))
            with db.tx() as c:
                c.execute("UPDATE import_streams SET token_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (dev_a,))
            assert denied_turn("route-turn-token-expired") == "CONSENT_REQUIRED"
            with db.tx() as c:
                c.execute("UPDATE import_streams SET token_expires_at=%s WHERE id=%s",
                          (original_device["token_expires_at"], dev_a))

            # A lock event revokes the installation key under the same user
            # lock. A turn waiting behind that transaction must re-read the
            # revoked key and fail instead of creating a turn.
            lock_held, release_lock = threading.Event(), threading.Event()
            lock_errors, turn_errors, turn_created = [], [], []
            def revoke_for_lock():
                try:
                    with db.tx() as c:
                        webchat._user_lock(c, ua)
                        webchat._consent_revoke(c, ua, challenge_row["installation_id"])
                        lock_held.set()
                        if not release_lock.wait(3): raise TimeoutError("lock test gate")
                except BaseException as exc:
                    lock_errors.append(exc)
            def create_during_lock():
                try:
                    lock_held.wait(3)
                    turn_created.append(webchat.turn_create(ua, created_session, "during lock", "route-turn-lock-race",
                                                            connected=lambda _d: True, capable=lambda _s: True))
                except db.CrmError as exc:
                    turn_errors.append(exc.code)
            revoke_thread = threading.Thread(target=revoke_for_lock, daemon=True)
            turn_thread = threading.Thread(target=create_during_lock, daemon=True)
            revoke_thread.start(); assert lock_held.wait(3)
            turn_thread.start(); time.sleep(0.1)
            assert not turn_created, "turn passed user lock while lock-revoke transaction was open"
            release_lock.set(); revoke_thread.join(5); turn_thread.join(5)
            assert not revoke_thread.is_alive() and not turn_thread.is_alive() and not lock_errors, (lock_errors, turn_errors)
            assert turn_errors == ["CONSENT_REQUIRED"] and not turn_created, (turn_errors, turn_created)
            with db.tx() as c:
                c.execute("UPDATE desktop_consent_keys SET state=%s,revoked_at=%s WHERE id=%s",
                          (key_row["state"], key_row["revoked_at"], challenge_row["key_id"]))
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev_a, "provider": "claude", "model": "test-model",
                                                   "client_session_id": "route-r1"})
            assert r.status_code == 200 and r.json()["created"] is False and r.json()["session_id"] == created_session, r.text
            ok("동의 challenge → 세션 1회 소비 · 서명 동의된 턴 생성 · 미소비/만료/폐기/불일치/lock 경합 거부 · 만료된 요청 TTL 이후 세션은 유지")

            # 만료
            expiry_iss = {"installation_id": inst, "request_id": "route-expiry"}
            assert post(h, GRANT, dict(grant_body, request_id="route-expiry")).status_code == 201
            cl = post(h, ISSUE, expiry_iss, bearer).json()["claims"]
            with db.tx() as c:
                c.execute("UPDATE chat_consent_challenges SET expires_at=floor(extract(epoch from now()))::bigint - 1 WHERE nonce=%s", (cl["nonce"],))
            cl = dict(cl, expires_at=rows("SELECT expires_at FROM chat_consent_challenges WHERE nonce=%s", (cl["nonce"],))[0]["expires_at"])
            code(post(h, VERIFY, {"installation_id": inst, "nonce": cl["nonce"], "signature": sign(k1, cl)}, bearer), 409, "GRANT-EXPIRED")
            assert ch_state(cl["nonce"]) == "expired"

            # A verified challenge can expire after the Python check but before the final UPDATE.
            # Pause the synthetic worker in that exact gap and require the UPDATE to reject it.
            assert post(h, GRANT, dict(grant_body, request_id="route-proof-expiry-race")).status_code == 201
            cl = post(h, ISSUE, {"installation_id": inst, "request_id": "route-proof-expiry-race"}, bearer).json()["claims"]
            with db.tx() as c:
                exp = c.execute("UPDATE chat_consent_challenges SET expires_at=floor(extract(epoch from clock_timestamp()))::bigint + 2 "
                                "WHERE nonce=%s RETURNING expires_at", (cl["nonce"],)).fetchone()["expires_at"]
            cl = dict(cl, expires_at=exp)
            r = post(h, VERIFY, {"installation_id": inst, "nonce": cl["nonce"], "signature": sign(k1, cl)}, bearer)
            assert r.status_code == 200 and r.json()["state"] == "verified", r.text
            race_result, race_finished, checked_proof = {}, threading.Event(), threading.Event()
            original_db_clock = webchat._db_clock
            worker_name = "consume-after-proof-expiry"

            def expire_between_check_and_update(c):
                now = original_db_clock(c)
                if threading.current_thread().name == worker_name:
                    calls = getattr(threading.current_thread(), "_consent_clock_calls", 0) + 1
                    threading.current_thread()._consent_clock_calls = calls
                    if calls == 2:  # grant clock first, proof clock second
                        checked_proof.set()
                        _wait_until_db_epoch(exp)
                return now

            webchat._db_clock = expire_between_check_and_update

            def consume_after_proof_expiry():
                try:
                    race_result["value"] = _grant_consume(ua, dev_a, "claude", "test-model", "route-proof-expiry-race")
                except db.CrmError as e:
                    race_result["code"] = e.code
                except BaseException as e:
                    race_result["error"] = type(e).__name__
                finally:
                    race_finished.set()

            race_thread = threading.Thread(target=consume_after_proof_expiry, name=worker_name, daemon=True)
            try:
                race_thread.start()
                assert checked_proof.wait(timeout=3), "worker did not reach proof-expiry check"
                race_thread.join(timeout=5)
            finally:
                webchat._db_clock = original_db_clock
            assert not race_thread.is_alive() and race_finished.is_set(), race_result
            assert race_result.get("code") == "GRANT-EXPIRED", race_result
            assert _grant_state(ua, "route-proof-expiry-race") == "approved"
            ok("grant consume: verified proof row lock 대기 중 challenge 만료 시 소비도 원자 거부")

            # 승인 뒤 grant 자체가 만료되면 세션은 만들지 않고 기존 세션을 보존한다.
            approved_expiry = {"installation_id": inst, "request_id": "route-approved-expiry"}
            assert post(h, GRANT, dict(grant_body, request_id="route-approved-expiry")).status_code == 201
            cl = post(h, ISSUE, approved_expiry, bearer).json()["claims"]
            r = post(h, VERIFY, {"installation_id": inst, "nonce": cl["nonce"], "signature": sign(k1, cl)}, bearer)
            assert r.status_code == 200 and r.json()["state"] == "verified", r.text
            with db.tx() as c:
                c.execute("UPDATE chat_provider_grants SET created_at=clock_timestamp()-interval '10 minutes', "
                          "expires_at=clock_timestamp()-interval '1 second' WHERE user_id=%s AND request_id='route-approved-expiry'", (ua,))
            assert _code(lambda: webchat.session_new(ua, dev_a, "claude", "test-model", "route-approved-expiry", capability_ok=True)) == "GRANT-EXPIRED"
            assert _grant_state(ua, "route-approved-expiry") == "approved"
            assert rows("SELECT status FROM chat_sessions WHERE id=%s", (created_session,))[0]["status"] == "active"

            # PC 연결을 허용한 뒤 철회하면 승인 grant 도 세션을 만들 수 없다.
            b2 = post(h, BEGIN, {"installation_id": inst_2, "spki": spki(k2)}, bearer_a2).json()
            act2 = {"installation_id": inst_2, "key_id": b2["key_id"], "pop_signature": sign(k2, b2["claims"])}
            assert post(h, ACT, act2, bearer_a2).status_code == 200
            revoke_body = {"device_id": a2["device"]["id"], "provider": "claude", "model": "test-model", "request_id": "route-revoked-device"}
            assert post(h, GRANT, revoke_body).status_code == 201
            revoke_ch = post(h, ISSUE, {"installation_id": inst_2, "request_id": "route-revoked-device"}, bearer_a2).json()["claims"]
            r = post(h, VERIFY, {"installation_id": inst_2, "nonce": revoke_ch["nonce"], "signature": sign(k2, revoke_ch)}, bearer_a2)
            assert r.status_code == 200 and r.json()["state"] == "verified", r.text
            imports.device_revoke(ua, a2["device"]["id"])
            assert _code(lambda: webchat.session_new(ua, a2["device"]["id"], "claude", "test-model",
                                                      "route-revoked-device", capability_ok=True)) == "NOT-FOUND"
            assert _grant_state(ua, "route-revoked-device") == "approved"
            assert rows("SELECT status FROM chat_sessions WHERE id=%s", (created_session,))[0]["status"] == "active"

            # 폐기 — 남의 토큰·묶이지 않은 설치본은 못 하고, 맞는 묶음이면 키와 issued challenge 를 함께 폐기
            revoke_iss = {"installation_id": inst, "request_id": "route-revoke"}
            assert post(h, GRANT, dict(grant_body, request_id="route-revoke")).status_code == 201
            cl = post(h, ISSUE, revoke_iss, bearer).json()["claims"]
            code(post(h, REV, {"installation_id": inst}, foreign), 409, "CONSENT_REQUIRED")
            code(post(h, REV, {"installation_id": inst_x}, bearer), 409, "CONSENT_REQUIRED")
            code(post(h, REV, {"installation_id": inst}), 401, "AUTH-INVALID")
            assert n_keys("active") == 2 and ch_state(cl["nonce"]) == "issued"
            r = post(h, REV, {"installation_id": inst}, bearer)
            assert r.status_code == 200 and r.json() == {"revoked": 1}, r.text
            assert ch_state(cl["nonce"]) == "revoked" and n_keys("active") == 1
            code(post(h, VERIFY, {"installation_id": inst, "nonce": cl["nonce"], "signature": sign(k1, cl)}, bearer), 409, "GRANT-USED")
            code(post(h, ISSUE, iss, bearer), 409, "CONSENT_REQUIRED")   # active 키 없음
            assert _grant_state(ua, "route-r1") == "consumed" and webchat._desktop_verifier is None
            ok("동의 route: 만료 GRANT-EXPIRED · 폐기는 세션+Bearer+설치본 묶음 필요 · 폐기 뒤 challenge revoked·재발급 거절 · 기존 승인 유지")

            # A fresh isolated device tests the HTTP gateway's actual DB locks
            # without consuming/revoking the device used by the remaining chat tests.
            gateway_device = imports.device_connect(ua, "chat MCP race pc")
            gateway_bearer = "Bearer " + gateway_device["token"]
            gateway_inst = "di_" + secrets.token_hex(12)
            gateway_key = Ed25519PrivateKey.generate()
            gateway_spki = gateway_key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            with db.tx() as c:
                c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) "
                          "VALUES (%s,%s,'chat MCP race pc','darwin',%s)",
                          (ua, gateway_inst, gateway_device["device"]["id"]))
            webchat.grant_request(ua, gateway_device["device"]["id"], "claude", "test-model", "mcp-race")
            key_begin = webchat.consent_key_begin(ua, gateway_bearer, gateway_inst, gateway_spki)
            webchat.consent_key_activate(ua, gateway_bearer, gateway_inst, key_begin["key_id"],
                                         sign(gateway_key, key_begin["claims"]))
            challenge = webchat.consent_challenge_issue(ua, gateway_bearer, gateway_inst, "mcp-race")
            claim = challenge["claims"]
            webchat.consent_challenge_verify(ua, gateway_bearer, gateway_inst, claim["nonce"],
                                             sign(gateway_key, claim))
            mcp_session, _, _ = webchat.session_new(ua, gateway_device["device"]["id"], "claude", "test-model",
                                                     "mcp-race", capability_ok=True)
            gateway_dev = imports.authenticate(gateway_bearer)
            launch_turn = "ct_" + secrets.token_hex(12)
            with db.tx() as c:
                c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,'launch-auth-test')",
                          (launch_turn, mcp_session["session_id"]))

            # Exercise the real HTTP handler while readiness is patched only
            # in this synthetic test process. Production remains hard OFF.
            class McpRequest:
                def __init__(self, body, authorization=None):
                    self.headers = Headers({"authorization": authorization or gateway_bearer,
                                            "content-type": "application/json"})
                    self._body = json.dumps(body).encode()
                async def body(self): return self._body

            def mcp_value(response):
                value = json.loads(response.body)["result"]
                if "content" in value and value["content"] and "text" in value["content"][0]:
                    return json.loads(value["content"][0]["text"])
                return value

            def bound_mcp(body):
                return {"session_id": mcp_session["session_id"], "turn_id": dispatch_turn, **body}

            route = webchat.Routes(None, lambda _name, handler: handler)
            launch_req_body = {"session_id": mcp_session["session_id"], "turn_id": launch_turn}
            with patch("webchat.PROVIDER_LAUNCH_READY", False):
                launch_off = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
            assert launch_off.status_code == 503, launch_off.body
            with patch("webchat.PROVIDER_LAUNCH_READY", True), patch("webchat._chat_rate", return_value=None):
                launch_ok = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert launch_ok.status_code == 200, launch_ok.body
                launch_value = json.loads(launch_ok.body)
                assert launch_value["authorized"] is True
                launch_binding = launch_value["binding"]
                assert (launch_binding["user_id"], launch_binding["device_id"], launch_binding["session_id"],
                        launch_binding["turn_id"], launch_binding["provider"], launch_binding["model"]) == (
                            ua, gateway_device["device"]["id"], mcp_session["session_id"], launch_turn, "claude", "test-model")
                assert launch_binding["grant_id"] and launch_binding["consent_challenge_id"]
                assert set(launch_value["tools"].values()) <= {"read", "write", "decide", "purge"}
                assert launch_value["tools"].get("mcp__my-crm__find") == "read"
                # AI 하나로 A3: trash_purge 는 purge 등급으로 실린다(실행은 확인 카드뿐). 다른 op 은 purge 등급이 아니다
                assert launch_value["tools"].get("mcp__my-crm__trash_purge") == "purge"
                assert [n for n, t in launch_value["tools"].items() if t == "purge"] == ["mcp__my-crm__trash_purge"]
                assert gateway_bearer not in launch_ok.body.decode()
                forged = asyncio.run(route.launch_authorization(McpRequest(
                    {**launch_req_body, "uid": ua, "tools": ["purge"], "executable_sha256": "0" * 64})))
                assert forged.status_code == 400, forged.body
                foreign_turn = asyncio.run(route.launch_authorization(McpRequest(
                    {"session_id": mcp_session["session_id"], "turn_id": "ct_" + secrets.token_hex(12)})))
                assert foreign_turn.status_code == 409, foreign_turn.body
                unknown_session = asyncio.run(route.launch_authorization(McpRequest(
                    {"session_id": "cs_" + secrets.token_hex(12), "turn_id": launch_turn})))
                assert unknown_session.status_code == 409, unknown_session.body
                foreign_user = asyncio.run(route.launch_authorization(McpRequest(launch_req_body, authorization=foreign)))
                assert foreign_user.status_code == 409, foreign_user.body
                foreign_device = asyncio.run(route.launch_authorization(McpRequest(launch_req_body, authorization=bearer_a2)))
                assert foreign_device.status_code == 401, foreign_device.body  # revoked device token is rejected at auth
                # J(JD1): 허용 단위는 공급자 — 세션의 공급자가 허용과 다르면 거절(모델은 세션 고정값을 binding 에 그대로 싣는다)
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET provider='codex' WHERE id=%s", (mcp_session["session_id"],))
                wrong_provider = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert wrong_provider.status_code == 409, wrong_provider.body
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET provider='claude' WHERE id=%s", (mcp_session["session_id"],))
                challenge_state = rows("SELECT id,settled_at,expires_at FROM chat_consent_challenges WHERE user_id=%s "
                                        "AND grant_id=(SELECT id FROM chat_provider_grants WHERE user_id=%s AND request_id='mcp-race') "
                                        "AND state='verified'", (ua, ua))[0]
                original_launch_grant = rows("SELECT created_at,expires_at FROM chat_provider_grants "
                                              "WHERE user_id=%s AND request_id='mcp-race'", (ua,))[0]
                with db.tx() as c:
                    c.execute("UPDATE chat_provider_grants SET created_at=clock_timestamp()-interval '10 minutes', "
                              "consumed_at=clock_timestamp()-interval '5 seconds', "
                              "expires_at=clock_timestamp()-interval '1 second' WHERE user_id=%s AND request_id='mcp-race'", (ua,))
                expired_launch = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert expired_launch.status_code == 200, expired_launch.body  # request TTL elapsed after consumption does not expire a session
                with db.tx() as c:
                    c.execute("UPDATE chat_provider_grants SET created_at=%s,consumed_at=clock_timestamp(),expires_at=%s "
                              "WHERE user_id=%s AND request_id='mcp-race'",
                              (original_launch_grant["created_at"], original_launch_grant["expires_at"], ua))
                with db.tx() as c:
                    c.execute("UPDATE chat_consent_challenges SET expires_at=(extract(epoch from clock_timestamp())::bigint - 1) "
                              "WHERE user_id=%s AND grant_id=(SELECT id FROM chat_provider_grants WHERE user_id=%s AND request_id='mcp-race') "
                              "AND state='verified'", (ua, ua))
                    c.execute("UPDATE chat_provider_grants SET consumed_at=clock_timestamp()-interval '5 seconds' "
                              "WHERE user_id=%s AND request_id='mcp-race'", (ua,))
                expired_challenge = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert expired_challenge.status_code == 200, expired_challenge.body
                with db.tx() as c:
                    c.execute("UPDATE chat_consent_challenges SET expires_at=%s WHERE id=%s",
                              (challenge_state["expires_at"], challenge_state["id"]))
                    c.execute("UPDATE chat_provider_grants SET consumed_at=clock_timestamp() WHERE user_id=%s AND request_id='mcp-race'", (ua,))
                # J(JD3): 허용을 해제하면(웹 경로) 실행 중 턴의 다음 재확인이 거절된다. binding 의 grant_id, challenge_id = 허용 성립 근거
                launch_permit = rows("SELECT * FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider='claude'",
                                     (ua, gateway_device["device"]["id"]))[0]
                assert (launch_binding["grant_id"], launch_binding["consent_challenge_id"]) == (
                    launch_permit["grant_id"], launch_permit["challenge_id"]), launch_binding
                assert webchat.permit_revoke(ua, device_id=gateway_device["device"]["id"], provider="claude") == 1
                revoked_permit = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert revoked_permit.status_code == 409, revoked_permit.body
                # R-J2: 해제가 세션을 닫고 실행 중 턴을 끝냈다 — 아래 판정 시험을 위해 허용, 세션, 턴을 되돌린다
                assert rows("SELECT status FROM chat_sessions WHERE id=%s", (mcp_session["session_id"],))[0]["status"] == "closed"
                assert rows("SELECT status FROM chat_turns WHERE id=%s", (launch_turn,))[0]["status"] == "failed"
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET status='active' WHERE id=%s", (mcp_session["session_id"],))
                    c.execute("UPDATE chat_turns SET status='running', ended_at=NULL WHERE id=%s", (launch_turn,))
                with db.tx() as c:
                    c.execute("INSERT INTO chat_provider_permits (id,user_id,device_id,provider,installation_id,key_id,grant_id,challenge_id,created_at) "
                              "VALUES (%(id)s,%(user_id)s,%(device_id)s,%(provider)s,%(installation_id)s,%(key_id)s,%(grant_id)s,%(challenge_id)s,%(created_at)s)",
                              launch_permit)
                with db.tx() as c:
                    c.execute("UPDATE desktop_consent_keys SET state='revoked',revoked_at=now() WHERE id=%s",
                              (rows("SELECT key_id FROM chat_consent_challenges WHERE id=%s", (challenge_state["id"],))[0]["key_id"],))
                revoked_key = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert revoked_key.status_code == 409, revoked_key.body
                with db.tx() as c:
                    c.execute("UPDATE desktop_consent_keys SET state='active',revoked_at=NULL WHERE id=%s",
                              (rows("SELECT key_id FROM chat_consent_challenges WHERE id=%s", (challenge_state["id"],))[0]["key_id"],))
                    c.execute("UPDATE desktop_installations SET revoked_at=now() WHERE user_id=%s AND id=%s",
                              (ua, gateway_inst))
                revoked_install = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert revoked_install.status_code == 409, revoked_install.body
                with db.tx() as c:
                    c.execute("UPDATE desktop_installations SET revoked_at=NULL WHERE user_id=%s AND id=%s",
                              (ua, gateway_inst))
                session_created_at = rows("SELECT created_at FROM chat_sessions WHERE id=%s",
                                           (mcp_session["session_id"],))[0]["created_at"]
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET created_at=clock_timestamp()-interval '31 days' WHERE id=%s",
                              (mcp_session["session_id"],))
                old_session = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert old_session.status_code == 409, old_session.body
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET created_at=%s WHERE id=%s",
                              (session_created_at, mcp_session["session_id"]))
                    c.execute("UPDATE chat_turns SET status='done',ended_at=clock_timestamp() WHERE id=%s", (launch_turn,))
                completed_turn = asyncio.run(route.launch_authorization(McpRequest(launch_req_body)))
                assert completed_turn.status_code == 409, completed_turn.body
            dispatch_turn = "ct_" + secrets.token_hex(12)
            with db.tx() as c:
                c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,'dispatch-auth-test')",
                          (dispatch_turn, mcp_session["session_id"]))
            gateway_body = {"session_id": mcp_session["session_id"], "turn_id": dispatch_turn,
                            "tool": "read", "op": "state_get", "params": {}}
            with patch("chat_mcp_gateway.ATOMIC_DISPATCH_READY", True), \
                 patch.dict(os.environ, {"CRM_CHAT_MCP_ENABLED": "1", "CRM_WEBCHAT_ENABLED": "1", "CRM_TRASH_ENABLED": "1"}), \
                 patch("webchat._chat_rate", return_value=None):
                read_response = asyncio.run(route.chat_mcp(McpRequest(gateway_body)))
                assert read_response.status_code == 200, read_response.body
                assert gateway_bearer not in read_response.body.decode()
                missing_binding = asyncio.run(route.chat_mcp(McpRequest(
                    {"tool": "read", "op": "state_get", "params": {}})))
                assert missing_binding.status_code == 400, missing_binding.body
                wrong_session = asyncio.run(route.chat_mcp(McpRequest(
                    {**gateway_body, "session_id": "cs_" + secrets.token_hex(12)})))
                assert wrong_session.status_code == 409, wrong_session.body
                wrong_turn = asyncio.run(route.chat_mcp(McpRequest(
                    {**gateway_body, "turn_id": "ct_" + secrets.token_hex(12)})))
                assert wrong_turn.status_code == 409, wrong_turn.body
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET status='closed' WHERE id=%s",
                              (mcp_session["session_id"],))
                closed_session = asyncio.run(route.chat_mcp(McpRequest(gateway_body)))
                assert closed_session.status_code == 409, closed_session.body
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET status='active' WHERE id=%s",
                              (mcp_session["session_id"],))
                session_created_at = rows("SELECT created_at FROM chat_sessions WHERE id=%s",
                                           (mcp_session["session_id"],))[0]["created_at"]
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET created_at=clock_timestamp()-interval '31 days' WHERE id=%s",
                              (mcp_session["session_id"],))
                expired_session = asyncio.run(route.chat_mcp(McpRequest(gateway_body)))
                assert expired_session.status_code == 409, expired_session.body
                with db.tx() as c:
                    c.execute("UPDATE chat_sessions SET created_at=%s WHERE id=%s",
                              (session_created_at, mcp_session["session_id"]))
                with db.tx() as c:
                    c.execute("UPDATE chat_turns SET status='done',ended_at=clock_timestamp() WHERE id=%s", (dispatch_turn,))
                ended_turn = asyncio.run(route.chat_mcp(McpRequest(gateway_body)))
                assert ended_turn.status_code == 409, ended_turn.body
                with db.tx() as c:
                    c.execute("UPDATE chat_turns SET status='running',ended_at=NULL WHERE id=%s", (dispatch_turn,))

                write_params = {"title": "synthetic MCP record", "text": "synthetic route test"}
                with db.tx() as c:
                    c.execute("UPDATE users SET display_name='Synthetic MCP' WHERE id=%s", (ua,))
                write_response = asyncio.run(route.chat_mcp(McpRequest(
                    bound_mcp({"tool": "write", "op": "record_add", "params": write_params, "bind": "model-bind"}))))
                assert write_response.status_code == 200, write_response.body
                write_card = mcp_value(write_response)   # F1: write 는 바로 실행되지 않고 카드가 된다(모델 bind 무시)
                assert write_card["status"] == "pending_confirmation", write_card
                assert not rows("SELECT 1 FROM records WHERE user_id=%s AND title='synthetic MCP record'", (ua,))
                write_done = webchat.approval_confirm(ua, mcp_session["session_id"], write_card["approval_id"])
                assert write_done["status"] == "confirmed", write_done
                record_id = write_done["result"]["id"]
                preview_params = {"op": "trash_move", "params": {
                    "kind": "record", "target_id": record_id, "expected_revision": None}}
                preview_response = asyncio.run(route.chat_mcp(McpRequest(
                    bound_mcp({"tool": "read", "op": "decide_preview", "params": preview_params}))))
                assert preview_response.status_code == 200, preview_response.body
                bind = mcp_value(preview_response)["bind"]
                no_bind = asyncio.run(route.chat_mcp(McpRequest(
                    bound_mcp({"tool": "decide", "op": "trash_move", "params": preview_params["params"]}))))
                assert no_bind.status_code == 200, no_bind.body
                first_approval = mcp_value(no_bind)
                assert first_approval["status"] == "pending_confirmation", first_approval
                assert _code(lambda: db.trash_get(ua, "record", record_id)) == "NOT-FOUND"
                confirm = asyncio.run(route.chat_mcp(McpRequest(
                    bound_mcp({"tool": "decide", "op": "trash_move", "params": preview_params["params"], "bind": bind}))))
                assert confirm.status_code == 200, confirm.body
                assert _code(lambda: db.trash_get(ua, "record", record_id)) == "NOT-FOUND"
                second_approval = mcp_value(confirm)
                assert second_approval["status"] == "pending_confirmation", second_approval
                aid = first_approval["approval_id"]
                assert _code(lambda: webchat.approval_confirm(ub, mcp_session["session_id"], aid)) == "NOT-FOUND"
                consent_key_id = rows("SELECT key_id FROM chat_consent_challenges WHERE id=%s", (challenge_state["id"],))[0]["key_id"]
                assert webchat.consent_key_revoke(ua, gateway_inst) == 1
                assert _code(lambda: webchat.approval_confirm(ua, mcp_session["session_id"], aid)) == "CONSENT_REQUIRED"
                assert _code(lambda: db.trash_get(ua, "record", record_id)) == "NOT-FOUND"
                # J: 키 폐기는 그 설치본의 서 있는 허용도 지운다 — 키만 되살려도 허용은 돌아오지 않는다
                assert not rows("SELECT 1 FROM chat_provider_permits WHERE user_id=%s AND installation_id=%s", (ua, gateway_inst))
                with db.tx() as c:
                    c.execute("UPDATE desktop_consent_keys SET state='active',revoked_at=NULL WHERE id=%s", (consent_key_id,))
                assert _code(lambda: webchat.approval_confirm(ua, mcp_session["session_id"], aid)) == "CONSENT_REQUIRED"
                with db.tx() as c:
                    c.execute("INSERT INTO chat_provider_permits (id,user_id,device_id,provider,installation_id,key_id,grant_id,challenge_id,created_at) "
                              "VALUES (%(id)s,%(user_id)s,%(device_id)s,%(provider)s,%(installation_id)s,%(key_id)s,%(grant_id)s,%(challenge_id)s,%(created_at)s)",
                              launch_permit)
                assert webchat.approval_confirm(ua, mcp_session["session_id"], aid)["status"] == "confirmed"
                assert db.trash_get(ua, "record", record_id) is not None
                assert _code(lambda: webchat.approval_confirm(ua, mcp_session["session_id"], aid)) == "APPROVAL-CLOSED"

                # Confirmation and actual key revocation serialize on the user
                # lock. Once confirm has the lock, revocation must wait until
                # its transaction finishes; subsequent confirmations fail.
                race_record = db.record_add(ua, "synthetic approval race", "synthetic body")
                race = asyncio.run(route.chat_mcp(McpRequest(bound_mcp({
                    "tool": "decide", "op": "trash_move", "params": {
                        "kind": "record", "target_id": race_record["id"], "expected_revision": None}}))))
                assert race.status_code == 200, race.body
                race_aid = mcp_value(race)["approval_id"]
                entered, release, revoke_started, revoke_done = (threading.Event() for _ in range(4))
                outcomes, errors = [], []
                original_dispatch = facade.dispatch
                def paused_confirm_dispatch(*args, **kwargs):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("synthetic confirmation wait")
                    return original_dispatch(*args, **kwargs)
                def confirm_race():
                    try:
                        outcomes.append(webchat.approval_confirm(ua, mcp_session["session_id"], race_aid)["status"])
                    except BaseException as e:
                        errors.append(e)
                def revoke_race():
                    revoke_started.set()
                    try:
                        outcomes.append(webchat.consent_key_revoke(ua, gateway_inst))
                    except BaseException as e:
                        errors.append(e)
                    finally:
                        revoke_done.set()
                with patch.object(facade, "dispatch", side_effect=paused_confirm_dispatch):
                    confirming = threading.Thread(target=confirm_race)
                    confirming.start()
                    assert entered.wait(3)
                    revoking = threading.Thread(target=revoke_race)
                    revoking.start()
                    assert revoke_started.wait(3) and not revoke_done.wait(0.2)
                    release.set()
                    confirming.join(5)
                    revoking.join(5)
                assert not confirming.is_alive() and not revoking.is_alive() and not errors, errors
                assert len(outcomes) == 2 and "confirmed" in outcomes and 1 in outcomes, outcomes
                assert _code(lambda: webchat.approval_confirm(ua, mcp_session["session_id"], second_approval["approval_id"])) == "CONSENT_REQUIRED"
                with db.tx() as c:
                    c.execute("UPDATE desktop_consent_keys SET state='active',revoked_at=NULL WHERE id=%s", (consent_key_id,))
                    c.execute("INSERT INTO chat_provider_permits (id,user_id,device_id,provider,installation_id,key_id,grant_id,challenge_id,created_at) "
                              "VALUES (%(id)s,%(user_id)s,%(device_id)s,%(provider)s,%(installation_id)s,%(key_id)s,%(grant_id)s,%(challenge_id)s,%(created_at)s)",
                              launch_permit)

                purge_response = asyncio.run(route.chat_mcp(McpRequest(
                    bound_mcp({"tool": "purge", "op": "trash_purge", "params": {}}))))
                assert purge_response.status_code == 400, purge_response.body
                assert gateway_bearer not in purge_response.body.decode()

                with db.tx() as c:
                    before_count = c.execute("SELECT count(*) AS n FROM records WHERE user_id=%s", (ua,)).fetchone()["n"]
                    before_cards = c.execute("SELECT count(*) AS n FROM chat_approvals WHERE user_id=%s", (ua,)).fetchone()["n"]
                real_prepare = webchat.chat_write_prepare
                def prepare_then_fail(*args, **kwargs):
                    real_prepare(*args, **kwargs)
                    raise RuntimeError("synthetic rollback after side effect")
                with patch.object(webchat, "chat_write_prepare", side_effect=prepare_then_fail):
                    rollback_response = asyncio.run(route.chat_mcp(McpRequest(
                        bound_mcp({"tool": "write", "op": "record_add", "params": {
                            "title": "synthetic rollback", "text": "must not persist"}}))))
                assert rollback_response.status_code == 400, rollback_response.body
                with db.tx() as c:
                    after_count = c.execute("SELECT count(*) AS n FROM records WHERE user_id=%s", (ua,)).fetchone()["n"]
                    after_cards = c.execute("SELECT count(*) AS n FROM chat_approvals WHERE user_id=%s", (ua,)).fetchone()["n"]
                assert (after_count, after_cards) == (before_count, before_cards), (before_count, after_count, before_cards, after_cards)

            def assert_gateway_scope_denied(dev=gateway_dev):
                with patch.object(facade, "dispatch_trusted") as denied_dispatch:
                    assert _code(lambda: webchat._chat_mcp_execute(dev, gateway_bearer, gateway_body)) == "CONSENT_REQUIRED"
                    denied_dispatch.assert_not_called()

            assert_gateway_scope_denied({**gateway_dev, "user_id": ub})  # cross-user principal data
            assert_gateway_scope_denied({**gateway_dev, "id": "is_" + secrets.token_hex(12)})  # cross-device
            original_grant = rows("SELECT created_at,expires_at,consumed_at FROM chat_provider_grants "
                                  "WHERE user_id=%s AND request_id='mcp-race'", (ua,))[0]
            with db.tx() as c:
                c.execute("UPDATE chat_provider_grants SET created_at=clock_timestamp()-interval '10 minutes', "
                          "consumed_at=clock_timestamp()-interval '5 seconds', "
                          "expires_at=clock_timestamp()-interval '1 second' "
                          "WHERE user_id=%s AND request_id='mcp-race'", (ua,))
            assert webchat._chat_mcp_execute(gateway_dev, gateway_bearer, gateway_body)
            with db.tx() as c:
                c.execute("UPDATE chat_provider_grants SET created_at=%s,consumed_at=%s,expires_at=%s "
                          "WHERE user_id=%s AND request_id='mcp-race'",
                          (original_grant["created_at"], original_grant["consumed_at"], original_grant["expires_at"], ua))
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET permit_id=%s WHERE id=%s", (webchat._id("cp"), mcp_session["session_id"]))
            assert_gateway_scope_denied()  # J: session no longer bound to the live standing permit
            with db.tx() as c:
                c.execute("UPDATE chat_sessions SET permit_id=%s WHERE id=%s", (launch_permit["id"], mcp_session["session_id"]))
            with db.tx() as c:
                c.execute("UPDATE desktop_consent_keys SET state='revoked',revoked_at=now() "
                          "WHERE user_id=%s AND installation_id=%s", (ua, gateway_inst))
            assert_gateway_scope_denied()  # revoked consent key
            with db.tx() as c:
                c.execute("UPDATE desktop_consent_keys SET state='active',revoked_at=NULL "
                          "WHERE user_id=%s AND installation_id=%s", (ua, gateway_inst))
            dispatch_entered, dispatch_release = threading.Event(), threading.Event()
            revoke_started, revoke_done = threading.Event(), threading.Event()
            dispatch_result, dispatch_error, revoke_error = [], [], []
            real_dispatch = facade.dispatch_trusted

            def paused_dispatch(*args, **kwargs):
                dispatch_entered.set()
                if not dispatch_release.wait(3):
                    raise TimeoutError("synthetic dispatch gate")
                return real_dispatch(*args, **kwargs)

            def run_mcp():
                try:
                    dispatch_result.append(webchat._chat_mcp_execute(
                        gateway_dev, gateway_bearer, gateway_body,
                    ))
                except BaseException as e:
                    dispatch_error.append(e)

            def revoke_gateway_device():
                revoke_started.set()
                try:
                    imports.device_revoke(ua, gateway_device["device"]["id"])
                except BaseException as e:
                    revoke_error.append(e)
                finally:
                    revoke_done.set()

            with patch.object(facade, "dispatch_trusted", side_effect=paused_dispatch):
                mcp_thread = threading.Thread(target=run_mcp, daemon=True)
                mcp_thread.start()
                assert dispatch_entered.wait(3), "gateway did not reach dispatch"
                revoke_thread = threading.Thread(target=revoke_gateway_device, daemon=True)
                revoke_thread.start()
                assert revoke_started.wait(2)
                assert not revoke_done.wait(0.15), "device revoke passed the held user lock"
                dispatch_release.set()
                mcp_thread.join(5)
                revoke_thread.join(5)
            assert not mcp_thread.is_alive() and not revoke_thread.is_alive(), "gateway/revoke deadlock"
            assert not dispatch_error and not revoke_error, (dispatch_error, revoke_error)
            assert dispatch_result and gateway_bearer not in json.dumps(dispatch_result[0]), "Bearer leaked into tool response"
            with patch("chat_mcp_gateway.ATOMIC_DISPATCH_READY", True), \
                 patch.dict(os.environ, {"CRM_CHAT_MCP_ENABLED": "1", "CRM_WEBCHAT_ENABLED": "1"}):
                revoked_http = asyncio.run(route.chat_mcp(McpRequest(gateway_body)))
            assert revoked_http.status_code == 401 and gateway_bearer not in revoked_http.body.decode()
            assert_gateway_scope_denied()  # device revoked after the previous atomic dispatch
            assert not rows("SELECT 1 FROM chat_provider_permits WHERE user_id=%s AND device_id=%s", (ua, gateway_device["device"]["id"])), \
                "J: PC 연결 해제는 그 장치의 서 있는 허용을 함께 지운다"
            ok("chat MCP 내부 통합: 실제 DB consumed grant scope · guarded read · 동시 device revoke 는 tx commit 뒤 진행 · 철회 뒤 거절 · Bearer 미노출")
    finally:
        with db.tx() as c:
            if dispatch_turn:
                c.execute("UPDATE chat_turns SET status='done',ended_at=clock_timestamp() WHERE id=%s AND status='running'",
                          (dispatch_turn,))
            if mcp_session:
                c.execute("DELETE FROM chat_sessions WHERE id=%s", (mcp_session["session_id"],))
            for session_id in (created_session, previous_id):
                if session_id:
                    c.execute("DELETE FROM chat_sessions WHERE id=%s", (session_id,))
            c.execute("DELETE FROM chat_consent_challenges WHERE user_id=%s", (ua,))
            c.execute("DELETE FROM chat_provider_permits WHERE user_id=%s", (ua,))
            c.execute("DELETE FROM desktop_consent_keys WHERE user_id=%s", (ua,))
            installations = [inst, inst_x, inst_2] + ([gateway_inst] if gateway_inst else [])
            c.execute("DELETE FROM desktop_installations WHERE user_id=%s AND id = ANY(%s)", (ua, installations))
            c.execute("DELETE FROM chat_provider_grants WHERE user_id=%s AND (request_id LIKE 'route-%%' OR request_id='mcp-race')", (ua,))
        imports.device_revoke(ub, other["device"]["id"])
        imports.device_revoke(ua, a2["device"]["id"])
        if gateway_device:
            imports.device_revoke(ua, gateway_device["device"]["id"])
        pc.close()


def test_standing_permit(srv):
    """대화 하나로 J(2026-11-12, JD1~JD3) — 서 있는 허용(사용자, 장치, 공급자). 합성 키, 합성 설치본만.
    첫 허용 한 번 뒤 같은 공급자의 새 대화와 다른 모델은 grant 없이, Codex 는 따로 한 번, 다른 공급자 동의 창(키 회전)과 거절은 허용을 지우지 않음,
    다른 장치와 다른 사용자 넘나들기 불가, grant 30일 정리는 허용을 지우지 않음(잠금, 재시작은 desktop 시험 몫), capabilities 허용 표시와 setup,
    해제 route(쿠키, Origin, 남의 것 404, 멱등) 뒤 그 공급자의 세션 CONSENT_REQUIRED, 다시 허용 = 새 행, 토큰 만료, 재발급, 장치 해제 = 허용 끝."""
    import base64
    import secrets
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import consent_signature

    def b64(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def sign(k, claims):
        return b64(k.sign(consent_signature.encode_consent(claims)))

    ua = db.user_by_email("wc-permit@example.com")["id"]
    ub = db.user_by_email("wc-permit-b@example.com")["id"]
    key = Ed25519PrivateKey.generate()
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    inst = "di_" + secrets.token_hex(12)
    pc = None
    try:
        with web(srv, ua) as h:
            assert h.get("/api/chat/capabilities").json() == {"devices": [], "setup": "none"}
        a = imports.device_connect(ua, "permit pc")
        dev, bearer = a["device"]["id"], "Bearer " + a["token"]
        dev2 = imports.device_connect(ua, "permit pc2")["device"]["id"]
        dev_b = imports.device_connect(ub, "permit b pc")["device"]["id"]
        with db.tx() as c:
            c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'permit pc','darwin',%s)",
                      (ua, inst, dev))
        with web(srv, ua) as h:
            assert h.get("/api/chat/capabilities").json() == {"devices": [], "setup": "offline"}
        ok("J 연결 안내 상태: PC 없음 = setup none, 등록됐으나 PC 앱 연결 없음 = offline")

        def consent(provider, model, rid, accept=True):
            """PC 앱 run() 흉내 — 동의 창마다 키 begin, activate(같은 키쌍 = 옛 키 rotate 서명) → challenge → 허용(verify) 또는 거절(consent.result)."""
            webchat.grant_request(ua, dev, provider, model, rid)
            b = webchat.consent_key_begin(ua, bearer, inst, der)
            webchat.consent_key_activate(ua, bearer, inst, b["key_id"], sign(key, b["claims"]), sign(key, dict(b["claims"], model="rotate")))
            ch = webchat.consent_challenge_issue(ua, bearer, inst, rid)["claims"]
            if accept:
                assert webchat.consent_challenge_verify(ua, bearer, inst, ch["nonce"], sign(key, ch))["state"] == "verified"
            else:
                assert webchat.consent_result({"user_id": ua, "id": dev}, rid, "declined") is True

        def new(model, rid, device=None, provider="claude", uid=None):
            return webchat.session_new(uid or ua, device or dev, provider, model, rid, capability_ok=True)

        def permit(provider="claude", device=None):
            r = rows("SELECT * FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider=%s", (ua, device or dev, provider))
            return r[0] if r else None

        def bound(sid):
            return rows("SELECT permit_id FROM chat_sessions WHERE id=%s", (sid,))[0]["permit_id"]

        def turn(sid, cid):
            t = webchat.turn_create(ua, sid, "permit turn", cid, connected=lambda _d: True, capable=lambda _s: True)
            webchat.turn_fail(t["turn"]["id"], "TEST-CLEANUP")
            return t

        def no_grant(rid):
            return not rows("SELECT 1 FROM chat_provider_grants WHERE user_id=%s AND request_id=%s", (ua, rid))

        # 1. 첫 허용: grant 없이는 CONSENT_REQUIRED, 서명 검증된 grant 를 소비하며 허용이 선다
        assert _code(lambda: new("model-a", "permit-none")) == "CONSENT_REQUIRED" and permit() is None
        # 기본 모델(model null)로 첫 허용 — 서명 claims 의 model 은 표지 CONSENT_DEFAULT_MODEL(2026-11-12 메인 지시)
        consent("claude", None, "permit-1")
        signed = rows("SELECT ch.model FROM chat_consent_challenges ch JOIN chat_provider_grants g ON g.id=ch.grant_id "
                      "WHERE g.user_id=%s AND g.request_id='permit-1' AND ch.state='verified'", (ua,))
        assert [r["model"] for r in signed] == [webchat.CONSENT_DEFAULT_MODEL], signed
        s1, _, created = new(None, "permit-1")
        p1 = permit()
        assert created and p1 and bound(s1["session_id"]) == p1["id"] and p1["installation_id"] == inst and s1["model"] is None
        turn(s1["session_id"], "permit-t1")
        # R-J1(보안 검토 발견 4): ':'로 시작하는 모델 = 서버 내부 표지(":default"). grant 요청과 세션 생성(허용이 서 있어도) 모두 ARG-INVALID
        for bad in (webchat.CONSENT_DEFAULT_MODEL, ":x"):
            assert _code(lambda: webchat.grant_request(ua, dev, "claude", bad, "permit-colon")) == "ARG-INVALID", bad
            assert _code(lambda: new(bad, "permit-colon")) == "ARG-INVALID", bad
        assert no_grant("permit-colon") and rows("SELECT 1 FROM chat_sessions WHERE id=%s AND status='active'", (s1["session_id"],))
        with web(srv, ua) as h:
            r = h.post("/api/chat/grants", json={"device_id": dev, "provider": "claude", "model": webchat.CONSENT_DEFAULT_MODEL,
                                                 "request_id": "permit-colon-route"})
            assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", r.text
        assert webchat.MODEL_RE.fullmatch("model:a"), "가운데 ':' 는 받는다"
        # PC 가 ':'로 시작하는 모델을 알리면 그 모델만 뺀다(공급자의 다른 모델은 남는다). 그것뿐이면 공급자도 없다. 다른 잘못된 값은 공급자를 버린다(그대로)
        assert webchat._normalize_capabilities([{"provider": "claude", "models": [":default", "claude-haiku-5-5"]}]) == [
            {"provider": "claude", "models": ["claude-haiku-5-5"]}]
        assert webchat._normalize_capabilities([{"provider": "claude", "models": [":default"]}]) == []
        assert webchat._normalize_capabilities([{"provider": "claude", "models": ["bad model", "claude-haiku-5-5"]}]) == []
        ok("J R-J1: ':'로 시작하는 모델(:default 표지) = grant 요청, 세션 생성에서 거절, PC 선택지에서는 그 모델만 뺀다")
        # 2. 같은 공급자의 다른 모델, 새 대화 = 동의 창 없이(grant 를 만들지 않는다). 모델 고정(결정 3)은 그대로 — 새 세션이다
        s2, closed, created = new("model-b", "permit-2-no-grant")
        assert created and no_grant("permit-2-no-grant") and bound(s2["session_id"]) == p1["id"] and s2["model"] == "model-b"
        assert rows("SELECT status FROM chat_sessions WHERE id=%s", (s1["session_id"],))[0]["status"] == "closed"
        s3, _, created = new("model-a", "permit-3-no-grant")
        assert created and no_grant("permit-3-no-grant")
        turn(s3["session_id"], "permit-t3")
        ok("J 서 있는 허용: 기본 모델로 첫 허용 한 번 → 같은 공급자의 다른 모델, 새 대화는 grant 없이 열린다, 세션 모델 고정은 그대로")

        # 3. Codex 는 따로 한 번. 그 동의 창(키 회전)과 거절은 Claude 허용을 지우지 않는다
        assert _code(lambda: new("gpt-x", "codex-none", provider="codex")) == "CONSENT_REQUIRED"
        consent("codex", "gpt-x", "codex-declined", accept=False)
        moved = permit()
        assert moved["id"] == p1["id"] and moved["key_id"] != p1["key_id"], "회전한 키로 허용을 옮긴다"
        assert rows("SELECT state FROM desktop_consent_keys WHERE id=%s", (moved["key_id"],))[0]["state"] == "active"
        assert rows("SELECT state FROM desktop_consent_keys WHERE id=%s", (p1["key_id"],))[0]["state"] == "revoked"
        s4, _, created = new("model-b", "permit-after-codex-decline")
        assert created and no_grant("permit-after-codex-decline") and permit("codex") is None
        consent("codex", "gpt-x", "codex-1")
        s5, _, created = new("gpt-x", "codex-1", provider="codex")
        assert created and permit("codex") and bound(s5["session_id"]) == permit("codex")["id"]
        s6, _, created = new("model-a", "permit-after-codex")
        assert created and no_grant("permit-after-codex") and bound(s6["session_id"]) == p1["id"]
        ok("J Codex 는 따로 한 번, 다른 공급자 동의 창의 키 회전과 거절 뒤에도 Claude 허용 유지(허용을 새 키로 옮김)")

        # 4. 넘나들기 불가 — 다른 장치는 허용이 없고, 다른 사용자는 이 장치와 설치본을 못 쓰고 못 지운다
        assert _code(lambda: new("model-a", "permit-dev2", device=dev2)) == "CONSENT_REQUIRED"
        assert _code(lambda: new("model-a", "permit-ub", uid=ub)) == "NOT-FOUND"
        assert _code(lambda: new("model-a", "permit-ub-own", device=dev_b, uid=ub)) == "CONSENT_REQUIRED"
        assert _code(lambda: webchat.permit_revoke(ub, device_id=dev, provider="claude")) == "NOT-FOUND"
        assert _code(lambda: webchat.permit_revoke(ub, installation_id=inst)) == "NOT-FOUND"
        assert permit() and permit("codex")
        ok("J 허용 넘나들기 불가: 다른 장치 = 다시 허용 필요, 다른 사용자 = 이 PC 로 세션도 해제도 못 함(NOT-FOUND)")

        # 5. 30일 정리(grant, challenge)는 허용을 지우지 않는다(JD2 의 서버 쪽. 잠금, 재시작 때 PC 앱이 폐기하지 않는 것은 desktop 시험 몫)
        with db.tx() as c:
            c.execute("UPDATE chat_consent_challenges SET created_at=now() - interval '31 days' WHERE user_id=%s", (ua,))
            c.execute("UPDATE chat_provider_grants SET created_at=now() - interval '31 days', expires_at=now() - interval '30 days' "
                      "WHERE user_id=%s", (ua,))
        webchat.purge()
        assert not rows("SELECT 1 FROM chat_provider_grants WHERE user_id=%s", (ua,)), "grant 는 30일 정리 대상(R8)"
        assert permit()["id"] == p1["id"] and permit("codex"), "허용은 30일 정리 대상이 아니다"
        s7, _, created = new("model-b", "permit-after-purge")
        assert created
        turn(s7["session_id"], "permit-t7")
        ok("J 허용은 grant, challenge 30일 정리 뒤에도 남고 새 대화를 연다(서버 쪽만. 잠금과 재시작에 폐기하지 않는 것은 desktop 시험 몫)")

        # 6. capabilities 허용 표시, 조회, 해제 route
        pc = PC(srv, a["token"], capabilities=[{"provider": "claude", "models": ["model-a", "model-b"]},
                                                {"provider": "codex", "models": ["gpt-x"]}])
        time.sleep(0.15)
        with web(srv, ua) as h:
            caps = h.get("/api/chat/capabilities").json()
            assert caps["setup"] == "ready" and [d["allowed_providers"] for d in caps["devices"]] == [["claude", "codex"]], caps
            listed = h.get("/api/chat/permits")
            assert listed.status_code == 200 and listed.headers.get("cache-control") == "no-store"
            assert sorted((x["device_id"], x["installation_id"], x["provider"]) for x in listed.json()["permits"]) == [
                (dev, inst, "claude"), (dev, inst, "codex")], listed.json()
            REV = "/api/chat/permits/revoke"
            for body in ({"device_id": dev, "installation_id": inst, "provider": "claude"}, {"provider": "claude"},
                         {"device_id": dev, "provider": "gemini"}, {"device_id": dev}, {"device_id": dev, "provider": "claude", "user_id": ua},
                         {"installation_id": "di_bad", "provider": None}):
                r = h.post(REV, json=body)
                assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", (body, r.text)
            r = h.post(REV, json={"device_id": dev, "provider": "claude"}, headers={"origin": "https://evil.example"})
            assert r.status_code == 403 and r.json()["code"] == "ORIGIN", r.text
        with web(srv) as h:
            r = h.post(REV, json={"device_id": dev, "provider": "claude"})
            assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED", r.text
        with web(srv, ub) as h:
            r = h.post(REV, json={"device_id": dev, "provider": "claude"})
            assert r.status_code == 404 and r.json()["code"] == "NOT-FOUND" and dev not in r.text, r.text
            assert h.get("/api/chat/permits").json() == {"permits": []}
        assert permit() and permit("codex")
        # R-J2(보안 검토 발견 1): 해제는 그 (장치, 공급자)의 실행 중 턴에 turn.stop 을 보내고 세션을 같은 트랜잭션에서 닫는다. 다른 공급자 해제는 건드리지 않는다
        running = webchat.turn_create(ua, s7["session_id"], "permit running", "permit-t-running",
                                      connected=lambda _d: True, capable=lambda _s: True)["turn"]["id"]
        codex_row = permit("codex")
        with web(srv, ua) as h:
            assert h.post(REV, json={"device_id": dev, "provider": "codex"}).json() == {"revoked": 1}
        assert not pc.wait(lambda m: m["type"] == "turn.stop", 0.5), "Codex 해제는 Claude 턴을 멈추지 않는다"
        assert rows("SELECT status FROM chat_turns WHERE id=%s", (running,))[0]["status"] == "running"
        assert rows("SELECT status FROM chat_sessions WHERE id=%s", (s7["session_id"],))[0]["status"] == "active"
        with db.tx() as c:   # Codex 허용 되돌리기(아래 시험이 쓴다)
            c.execute("INSERT INTO chat_provider_permits (id,user_id,device_id,provider,installation_id,key_id,grant_id,challenge_id,created_at) "
                      "VALUES (%(id)s,%(user_id)s,%(device_id)s,%(provider)s,%(installation_id)s,%(key_id)s,%(grant_id)s,%(challenge_id)s,%(created_at)s)",
                      codex_row)
        with web(srv, ua) as h:
            r = h.post(REV, json={"device_id": dev, "provider": "claude"})
            assert r.status_code == 200 and r.json() == {"revoked": 1} and r.headers.get("cache-control") == "no-store", r.text
            assert pc.wait(lambda m: m["type"] == "turn.stop" and m["turn_id"] == running, 3), "해제 = PC 에 turn.stop"
            assert h.post(REV, json={"device_id": dev, "provider": "claude"}).json() == {"revoked": 0}, "멱등"
            assert [d["allowed_providers"] for d in h.get("/api/chat/capabilities").json()["devices"]] == [["codex"]]
        assert rows("SELECT status FROM chat_turns WHERE id=%s", (running,))[0]["status"] == "failed"
        assert rows("SELECT data FROM chat_events WHERE turn_id=%s ORDER BY seq DESC LIMIT 1", (running,))[0]["data"] == {"code": "CONSENT_REQUIRED"}
        assert rows("SELECT status FROM chat_sessions WHERE id=%s", (s7["session_id"],))[0]["status"] == "closed"
        assert _code(lambda: turn(s7["session_id"], "permit-t-revoked")) == "SESSION-CLOSED", "해제 뒤 열린 Claude 세션 = 닫힘"
        assert _code(lambda: new("model-a", "permit-after-revoke")) == "CONSENT_REQUIRED", "해제 뒤 새 Claude 대화 = 다시 허용"
        s8, _, created = new("gpt-x", "codex-after-claude-revoke", provider="codex")
        assert created, "다른 공급자 허용은 그대로"
        with web(srv, ua) as h:   # PC 앱 꼴: 설치본 + 공급자 null = 그 PC 전부
            r = h.post(REV, json={"installation_id": inst, "provider": None})
            assert r.status_code == 200 and r.json() == {"revoked": 1}, r.text
        assert _code(lambda: turn(s8["session_id"], "permit-t-codex-revoked")) == "SESSION-CLOSED"
        assert permit() is None and permit("codex") is None
        ok("J 해제 route: 쿠키 + Origin(403), 세션 없음 401, 남의 장치 404, 본문 엄격, 멱등, capabilities 반영, 설치본 + null = 전부")
        ok("J R-J2: 해제 = 그 공급자의 실행 중 턴에 turn.stop + 세션 닫힘(턴 failed CONSENT_REQUIRED), 다른 공급자 해제는 그대로, 새 대화 CONSENT_REQUIRED")

        # 7. 다시 허용 = 새 허용 행(새 id). 해제 전 세션은 다시 살아나지 않는다
        consent("claude", "model-a", "permit-again")
        s9, _, created = new("model-a", "permit-again")
        p2 = permit()
        assert created and p2["id"] != p1["id"] and bound(s9["session_id"]) == p2["id"]
        with db.tx() as c:
            c.execute("UPDATE chat_sessions SET status='closed' WHERE id=%s", (s9["session_id"],))
            c.execute("UPDATE chat_sessions SET status='active' WHERE id=%s", (s7["session_id"],))
        assert _code(lambda: turn(s7["session_id"], "permit-t-old")) == "CONSENT_REQUIRED"
        with db.tx() as c:
            c.execute("UPDATE chat_sessions SET status='closed' WHERE id=%s", (s7["session_id"],))
            c.execute("UPDATE chat_sessions SET status='active' WHERE id=%s", (s9["session_id"],))
        ok("J 다시 허용 = 새 허용 행, 해제 전 허용에 묶인 세션은 살아나지 않는다")

        # 8. 토큰: 살아 있는 토큰 교체(agent rotate)는 유지, 만료 = 판정 실패, 만료 뒤 새 토큰으로 되살리지 않음
        with db.tx() as c:
            imports.pending_in(c, ua, dev)
        assert permit()["id"] == p2["id"], "살아 있는 토큰 교체는 허용을 지우지 않는다"
        expires = rows("SELECT token_expires_at FROM import_streams WHERE id=%s", (dev,))[0]["token_expires_at"]
        with db.tx() as c:
            c.execute("UPDATE import_streams SET token_expires_at=clock_timestamp() - interval '1 second' WHERE id=%s", (dev,))
        assert _code(lambda: new("model-b", "permit-token-expired")) == "CONSENT_REQUIRED"
        with db.tx() as c:
            imports.pending_in(c, ua, dev)
            c.execute("UPDATE import_streams SET token_expires_at=%s WHERE id=%s", (expires, dev))
        assert permit() is None, "만료된 토큰을 새 토큰으로 바꿔도 허용은 되살아나지 않는다"
        # 8-1. 만료 전에 받아 둔 대기 토큰을 만료 뒤에 처음 써도(authenticate 승격) 허용은 되살아나지 않는다
        consent("claude", "model-a", "permit-pending")
        new("model-a", "permit-pending")
        assert permit()
        with db.tx() as c:
            pend, _ = imports.pending_in(c, ua, dev)
        assert permit(), "살아 있는 토큰일 때 받은 대기 토큰 = 허용 유지"
        with db.tx() as c:
            c.execute("UPDATE import_streams SET token_expires_at=clock_timestamp() - interval '1 second' WHERE id=%s", (dev,))
        imports.authenticate("Bearer " + pend)
        assert permit() is None, "만료 뒤 대기 토큰 승격 = 허용 끝"
        bearer = "Bearer " + pend
        # 9. 웹 토큰 재발급과 PC 연결 해제도 허용을 지운다
        consent("claude", "model-a", "permit-reissue")
        new("model-a", "permit-reissue")
        assert permit()
        imports.device_reissue(ua, dev)
        assert permit() is None
        consent("claude", "model-a", "permit-unlink")
        new("model-a", "permit-unlink")
        assert permit()
        imports.device_revoke(ua, dev)
        assert permit() is None
        ok("J 허용 끝: 토큰 만료(판정 실패, 새 토큰으로 안 살아남, 만료 뒤 대기 토큰 승격도 같음, 살아 있는 토큰 교체는 유지), 웹 토큰 재발급, PC 연결 해제")
    finally:
        if pc:
            pc.close()
        for uid in (ua, ub):
            with db.tx() as c:
                c.execute("DELETE FROM admin_audit WHERE actor_id=%s OR target_id=%s", (uid, uid))
            db.user_delete(uid)


def test_ai_links(srv):
    """앱 하나 1.3(2026-11-13) — 새 앱은 hello.ai_links 로 공급자 인증 상태를 알린다. linked = grant, 허용 창, 서명 없이 서 있는 허용(basis device),
    그 밖 = 허용을 지우고 열린 세션을 닫는다. capabilities 에 ai_links 와 setup no_link. launch-authorization 의 binding 꼴은 그대로(id = 허용 행).
    장치 토큰 폐기 = 허용 끝. 옛 앱(ai_links 없음)은 지금 consent 흐름 그대로(위 시험들)."""
    uid = db.user_by_email("wc-link@example.com")["id"]
    a = imports.device_connect(uid, "link pc")
    dev, tok = a["device"]["id"], a["token"]
    caps = [{"provider": "claude", "models": ["sonnet"]}]

    def permits():
        return rows("SELECT provider, basis, installation_id, key_id, grant_id, challenge_id FROM chat_provider_permits WHERE user_id=%s ORDER BY provider", (uid,))

    def wait_for(pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            time.sleep(0.05)
        return False

    assert webchat.normalize_ai_links(None) is None
    assert webchat.normalize_ai_links({"claude": "linked", "codex": "hacked", "x": "linked"}) == {"claude": "linked", "codex": "missing"}
    assert webchat.normalize_ai_links("linked") == {"claude": "missing", "codex": "missing"}
    pc = PC(srv, tok, capabilities=caps)
    try:
        pc.send({"type": "hello", "agent_version": "0.1.7", "providers": ["claude"], "capabilities_version": 2, "capabilities": caps,
                 "ai_links": {"claude": "signed_out"}})
        time.sleep(0.2)
        with web(srv, uid) as h:
            body = h.get("/api/chat/capabilities").json()
            assert body["setup"] == "no_link" and body["devices"][0]["ai_links"] == {"claude": "signed_out", "codex": "missing"}, body
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev, "provider": "claude", "model": "sonnet",
                                                   "client_session_id": "link-denied"})
            assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED", r.text
        assert permits() == []
        ok("앱 하나 1.3: 새 앱 + 로그인 안 됨 = setup no_link, 세션 거절(CONSENT_REQUIRED), 허용 없음")

        pc.send({"type": "hello", "agent_version": "0.1.7", "providers": ["claude"], "capabilities_version": 2, "capabilities": caps,
                 "ai_links": {"claude": "linked"}})
        assert wait_for(lambda: len(permits()) == 1), permits()
        p = permits()[0]
        assert (p["provider"], p["basis"], p["installation_id"], p["key_id"], p["grant_id"], p["challenge_id"]) == ("claude", "device", None, None, None, None)
        with web(srv, uid) as h:
            body = h.get("/api/chat/capabilities").json()
            assert body["setup"] == "ready" and body["devices"][0]["allowed_providers"] == ["claude"], body
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev, "provider": "claude", "model": "sonnet",
                                                   "client_session_id": "link-ok"})
            assert r.status_code in (200, 201), r.text
            sid = r.json()["session_id"]
        assert rows("SELECT count(*) AS n FROM chat_provider_grants WHERE user_id=%s", (uid,))[0]["n"] == 0, "grant 없이"
        assert rows("SELECT count(*) AS n FROM chat_consent_challenges WHERE user_id=%s", (uid,))[0]["n"] == 0, "서명 없이"
        # 같은 linked 를 다시 알려도 허용 행은 그대로(세션이 묶인 id 가 바뀌지 않는다)
        before = rows("SELECT id FROM chat_provider_permits WHERE user_id=%s", (uid,))[0]["id"]
        pc.send({"type": "hello", "agent_version": "0.1.7", "providers": ["claude"], "capabilities_version": 2, "capabilities": caps,
                 "ai_links": {"claude": "linked"}})
        time.sleep(0.2)
        assert rows("SELECT id FROM chat_provider_permits WHERE user_id=%s", (uid,))[0]["id"] == before
        ok("앱 하나 1.3: linked = 허용 행(basis device, 서명 근거 넷 NULL) · grant, challenge 0 으로 세션 · 다시 알려도 같은 행")

        turn = "ct_" + secrets.token_hex(12)
        with db.tx() as c:
            c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,'link-launch')", (turn, sid))
        out = webchat._chat_launch_authorization(imports.authenticate("Bearer " + tok), "Bearer " + tok, sid, turn)
        assert out["authorized"] is True and out["binding"]["grant_id"] == before == out["binding"]["consent_challenge_id"], out["binding"]
        assert out["binding"]["provider"] == "claude" and out["binding"]["model"] == "sonnet"
        ok("앱 하나 1.3: launch-authorization binding 꼴 그대로 — grant_id, consent_challenge_id = 허용 행 id(비지 않은 문자열)")

        pc.send({"type": "hello", "agent_version": "0.1.7", "providers": ["claude"], "capabilities_version": 2, "capabilities": caps,
                 "ai_links": {"claude": "off"}})
        stop = pc.wait(lambda m: m.get("type") == "turn.stop" and m.get("turn_id") == turn)
        assert stop, "끊기 = 실행 중 턴에 turn.stop"
        assert wait_for(lambda: permits() == [])
        assert rows("SELECT status FROM chat_sessions WHERE id=%s", (sid,))[0]["status"] != "active"
        with web(srv, uid) as h:
            assert h.get("/api/chat/capabilities").json()["setup"] == "no_link"
        ok("앱 하나 1.3: off(연결 끊기) = 허용 지움, 열린 세션 닫힘, 실행 중 턴 turn.stop, setup no_link")

        pc.send({"type": "hello", "agent_version": "0.1.7", "providers": ["claude"], "capabilities_version": 2, "capabilities": caps,
                 "ai_links": {"claude": "linked"}})
        assert wait_for(lambda: len(permits()) == 1)
    finally:
        pc.close()
    old_app = PC(srv, tok, capabilities=caps)   # 옛 앱이 같은 장치로 붙음(ai_links 없는 hello) = device 근거 허용을 지운다(열린 쪽으로 남지 않게)
    try:
        assert wait_for(lambda: permits() == []), permits()
        with web(srv, uid) as h:
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev, "provider": "claude", "model": "sonnet",
                                                   "client_session_id": "link-legacy"})
            assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED", r.text
    finally:
        old_app.close()
    ok("앱 하나 1.3: ai_links 없는 hello(옛 앱) = device 근거 허용 지움 → 옛 consent 흐름(CONSENT_REQUIRED)")
    pc = PC(srv, tok, capabilities=caps)
    try:
        pc.send({"type": "hello", "agent_version": "0.1.7", "providers": ["claude"], "capabilities_version": 2, "capabilities": caps,
                 "ai_links": {"claude": "linked"}})
        assert wait_for(lambda: len(permits()) == 1)
    finally:
        pc.close()
    imports.device_revoke(uid, dev)
    with db.tx() as c:
        assert webchat._permit_live(c, uid, dev, "claude", lock=False) is None
    ok("앱 하나 1.3: 장치 해제 = device 근거 허용도 끝(판정 하나 _permit_live)")


def test_unapproved_keeps_active(srv, ua, tok_a, dev_a):
    """회귀: 승인 없는 실제 공급자 새 대화 요청은 기존 active 세션을 닫지 않는다(grant 요청이 있어도)."""
    sid = webchat._id("cs")
    pc = PC(srv, tok_a, capabilities=[{"provider": "fake", "models": [None, "fake-test"]},
                                     {"provider": "claude", "models": ["test-model"]},
                                     {"provider": "codex", "models": ["test-model"]}])
    try:
        with db.tx() as c:
            c.execute("UPDATE chat_sessions SET status='closed' WHERE user_id=%s AND status='active'", (ua,))
            c.execute("INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version) "
                      "VALUES (%s,%s,%s,'fake',NULL,'keep-active',2)", (sid, ua, dev_a))
        for prov in ("claude", "codex"):
            assert _code(lambda: webchat.session_new(ua, dev_a, prov, "test-model", f"unapproved-{prov}", capability_ok=True)) == "CONSENT_REQUIRED"
        webchat.grant_request(ua, dev_a, "claude", "test-model", "grant-keep")   # pending grant 만으로는 열리지 않는다
        assert _code(lambda: webchat.session_new(ua, dev_a, "claude", "test-model", "unapproved-pending", capability_ok=True)) == "CONSENT_REQUIRED"
        with web(srv, ua) as h:
            r = h.post("/api/chat/sessions", json={"operation": "new", "device_id": dev_a, "provider": "claude", "model": "test-model",
                                                   "client_session_id": "unapproved-http"})
            assert r.status_code == 409 and r.json()["code"] == "CONSENT_REQUIRED", r.text
        assert rows("SELECT status FROM chat_sessions WHERE id=%s", (sid,))[0]["status"] == "active"
        assert rows("SELECT count(*) AS n FROM chat_sessions WHERE user_id=%s AND status='active'", (ua,))[0]["n"] == 1
        assert rows("SELECT count(*) AS n FROM chat_sessions WHERE user_id=%s AND client_session_id LIKE 'unapproved-%%'", (ua,))[0]["n"] == 0
        assert _grant_state(ua, "grant-keep") == "pending"
        ok("회귀: 미승인 claude·codex 새 대화(직접·HTTP·pending grant)는 기존 active 세션을 닫지 않는다")
    finally:
        pc.close()
        with db.tx() as c:
            c.execute("DELETE FROM chat_provider_grants WHERE user_id=%s AND request_id='grant-keep'", (ua,))
            c.execute("DELETE FROM chat_sessions WHERE id=%s", (sid,))


def test_fake_not_advertised_outside_dev():
    old = os.environ.get("CRM_DEV")
    os.environ["CRM_DEV"] = "0"
    try:
        assert webchat._normalize_capabilities([{"provider": "fake", "models": [None]}]) == []
    finally:
        if old is None:
            os.environ.pop("CRM_DEV", None)
        else:
            os.environ["CRM_DEV"] = old
    ok("fake capability는 dev 시험 장치에서만 허용")


def test_sessions(srv, ua, ub, tok_a, dev_a, dev_b2):
    cols = {r["column_name"] for r in rows("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='chat_sessions'")}
    assert {"model", "client_session_id", "binding_version"} <= cols, cols
    indexes = {r["indexname"] for r in rows("SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() AND tablename='chat_sessions'")}
    assert "ux_chat_sessions_client" in indexes, indexes
    pc = PC(srv, tok_a)
    with web(srv, ua) as h:
        payload = {"operation": "new", "device_id": dev_a, "provider": "fake", "model": None, "client_session_id": "test-session-a"}
        r = h.post("/api/chat/sessions", json=payload)
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["status"] == "active" and s["connected"] is True and s["session_id"].startswith("cs_")
        assert s["provider"] == "fake" and s["model"] is None and s["binding_version"] == 2
        assert h.post("/api/chat/sessions", json=payload).json()["session_id"] == s["session_id"], "같은 client_session_id 요청은 멱등"
        conflict = dict(payload, provider="codex")
        r = h.post("/api/chat/sessions", json=conflict)
        assert r.status_code == 409 and r.json()["code"] == "SESSION-CONFLICT", r.text
        resumed = h.post("/api/chat/sessions", json={"operation": "resume", "session_id": s["session_id"]})
        assert resumed.status_code == 200 and resumed.json()["session_id"] == s["session_id"] and resumed.json()["binding_version"] == 2
        lst = h.get("/api/chat/sessions").json()["sessions"]
        assert [x["session_id"] for x in lst if x["status"] == "active"] == [s["session_id"]]
    pc.close()
    with web(srv, ua) as h:
        # Closing the client socket is asynchronous from the server's point of
        # view. Assert the offline behavior only after the hub has detached it.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            devices = h.get('/api/chat/capabilities').json()['devices']
            if not any(d['device_id'] == dev_a for d in devices):
                break
            time.sleep(0.02)
        else:
            raise AssertionError('server did not detach the closed device')
        repeated = h.post("/api/chat/sessions", json=payload)
        assert repeated.status_code == 200 and repeated.json()["session_id"] == s["session_id"], "중복 new는 장치 offline이어도 재실행하지 않는다"
        unavailable = dict(payload, client_session_id="offline-new-session")
        r = h.post("/api/chat/sessions", json=unavailable)
        assert r.status_code == 409 and r.json()["code"] == "PROVIDER-UNAVAILABLE", r.text
    with web(srv, ub) as h:   # 장치 2대 = 골라야 한다 · 고르면 된다
        r = h.post("/api/chat/sessions", json={})
        assert r.status_code == 400 and r.json()["code"] == "DEVICE-REQUIRED", r.text
        r = h.post("/api/chat/sessions", json={"device_id": "is_nope"})
        assert r.status_code == 404
        sb = h.post("/api/chat/sessions", json={"device_id": dev_b2}).json()
        assert sb["device_id"] == dev_b2
        r = h.get(f"/api/chat/sessions/{s['session_id']}/messages")
        assert r.status_code == 404, "남의 세션 = 없음"
    ok("세션: 장치 1대 자동 · 활성 1(같은 세션) · 여러 대 400 DEVICE-REQUIRED · 고른 장치 · 남의 세션 404")
    return s["session_id"], sb["session_id"]


def test_turns(srv, ua, tok_a, sid):
    with web(srv, ua) as h:
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "안녕", "client_turn_id": "t-1"})
        assert r.status_code == 409 and r.json()["code"] == "DEVICE-OFFLINE", r.text
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "x" * (webchat.TEXT_MAX_CHARS + 1), "client_turn_id": "t-1"})
        assert r.status_code == 413 and r.json()["code"] == "TEXT-LIMIT"
        pc = PC(srv, tok_a)
        time.sleep(0.2)
        assert h.get("/api/chat/sessions").json()["sessions"][0]["connected"] is True
        did = rows("SELECT device_id FROM chat_sessions WHERE id=%s", (sid,))[0]["device_id"]
        pc.send({"type": "hello", "agent_version": "test", "providers": ["fake"], "capabilities_version": 2,
                 "capabilities": [{"provider": "codex", "models": [None]}]})
        for _ in range(50):
            d = webchat.hub.dev(ua, did)
            if d and d.capabilities and d.capabilities[0]["provider"] == "codex":
                break
            time.sleep(0.02)
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "잘못 고정된 공급자", "client_turn_id": "t-bind-rejected"})
        assert r.status_code == 409 and r.json()["code"] == "PROVIDER-UNAVAILABLE", r.text
        assert rows("SELECT count(*) AS n FROM chat_turns WHERE session_id=%s AND client_turn_id='t-bind-rejected'", (sid,))[0]["n"] == 0
        pc.send({"type": "hello", "agent_version": "test", "providers": ["fake"], "capabilities_version": 2,
                 "capabilities": [{"provider": "fake", "models": [None, "fake-test"]}]})
        time.sleep(0.1)
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "안녕 PC", "client_turn_id": "t-1"})
        assert r.status_code == 201 and r.json()["created"] is True, r.text
        tid = r.json()["turn_id"]
        st = pc.wait(lambda m: m["type"] == "turn.start")
        assert st and st["turn_id"] == tid and st["text"] == "안녕 PC" and st["session_id"] == sid and st["provider"] == "fake" and st["model"] is None and st["binding_version"] == 2 and "cli_session_ref" not in st
        r2 = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "안녕 PC", "client_turn_id": "t-1"})
        assert r2.status_code == 200 and r2.json() == {"turn_id": tid, "status": "running", "created": False}, r2.text
        assert pc.wait(lambda m: m["type"] == "turn.start", 0.5) is None, "멱등 — 다시 보내지 않는다"
        nr = h.post("/api/chat/sessions", json={"operation": "new", "device_id": rows("SELECT device_id FROM chat_sessions WHERE id=%s", (sid,))[0]["device_id"], "provider": "fake", "model": None, "client_session_id": "busy-new-session"})
        assert nr.status_code == 409 and nr.json()["code"] == "TURN-BUSY", nr.text
        r3 = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "또", "client_turn_id": "t-2"})
        assert r3.status_code == 409 and r3.json()["code"] == "TURN-BUSY"
        ok("턴: PC 꺼짐 409 DEVICE-OFFLINE · 8,001자 413 · 생성 201 + turn.start · 같은 client_turn_id = 같은 턴(재전송 없음) · 409 TURN-BUSY")

        sse = SSE(srv, ua, sid)
        assert sse.status == 200 and sse.headers["content-type"].startswith("text/event-stream") and sse.headers["cache-control"] == "no-store"
        evs, last = sse.until("turn")
        assert evs[0]["event"] == "pc" and evs[0]["data"]["connected"] is True
        assert last["id"] == f"{tid}:0" and last["data"]["text"] == "안녕 PC"

        pc.event(tid, 1, "delta", {"text": "하나 "})
        assert pc.ack(tid) == 1
        pc.event(tid, 1, "delta", {"text": "중복"})
        assert pc.ack(tid) == 1, "중복 seq = 무시 + 누적 ack"
        pc.event(tid, 3, "delta", {"text": "빈 칸"})
        assert pc.ack(tid) == 1, "빈 칸 seq = 저장 안 함"
        pc.send({"type": "session_ref", "session_id": sid, "cli_session_ref": "fake-ref-1"})
        pc.event(tid, 2, "tool_call", {"name": "find", "input": {}})
        assert pc.ack(tid) == 2
        e, _ = sse.until("tool_call")
        assert [x["id"] for x in e] == [f"{tid}:1", f"{tid}:2"] and e[0]["data"]["data"] == {"text": "하나 "}
        assert rows("SELECT count(*) AS n FROM chat_events WHERE turn_id=%s", (tid,))[0]["n"] == 2
        ok("PC 이벤트: 누적 ack · (turn_id,seq) 중복 무시 · 빈 칸 저장 안 함 · SSE 실시간 id=<turn>:<seq>")

        sse.close()   # Last-Event-ID 재개 — 끊긴 뒤 들어온 것부터
        pc.event(tid, 3, "delta", {"text": "둘"})
        pc.event(tid, 4, "done", {})
        assert pc.ack(tid) == 3 and pc.ack(tid) == 4
        sse = SSE(srv, ua, sid, last_id=f"{tid}:2")
        e, last = sse.until("done")
        assert [x["id"] for x in e if "id" in x] == [f"{tid}:3", f"{tid}:4"], e
        sse2 = SSE(srv, ua, sid)   # 사용자당 1 — 새 연결이 옛 연결을 닫는다
        e = sse.next(3)
        assert e and e["event"] == "replaced", ("옛 SSE 에 replaced 를 알린다", e)
        assert sse.next(3) is None, "옛 SSE 닫힘"
        e, _ = sse2.until("done")
        assert [x["event"] for x in e] == ["pc", "turn", "delta", "tool_call", "delta", "done"], [x["event"] for x in e]
        sse2.close()
        old_max, old_hb = webchat.SSE_MAX_SECONDS, webchat.HEARTBEAT_SECONDS
        webchat.SSE_MAX_SECONDS, webchat.HEARTBEAT_SECONDS = 0.5, 0.2
        try:
            sse3 = SSE(srv, ua, sid, last_id=f"{tid}:4")
            assert sse3.next()["event"] == "pc" and sse3.next(5) is None, "최대 수명 지나면 끝(브라우저가 다시 붙는다)"
            sse3.close()
        finally:
            webchat.SSE_MAX_SECONDS, webchat.HEARTBEAT_SECONDS = old_max, old_hb
        ok("SSE: Last-Event-ID 뒤부터 재생 · 처음 연결 = 전체 재생 · 사용자당 1(옛 연결에 replaced 뒤 닫힘) · 최대 수명 뒤 끝")

        t = rows("SELECT status, ended_at FROM chat_turns WHERE id=%s", (tid,))[0]
        assert t["status"] == "done" and t["ended_at"]
        m = h.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
        assert [(x["role"], x["body"]) for x in m] == [("user", "안녕 PC"), ("assistant", "하나 둘")], m
        assert h.get(f"/api/chat/sessions/{sid}/messages", params={"after": tid}).json()["messages"] == []
        assert rows("SELECT cli_session_ref FROM chat_sessions WHERE id=%s", (sid,))[0]["cli_session_ref"] == "fake-ref-1"
        pc.event(tid, 5, "delta", {"text": "늦게"})
        assert pc.ack(tid) == 5 and rows("SELECT count(*) AS n FROM chat_events WHERE turn_id=%s", (tid,))[0]["n"] == 4, "끝난 턴 = 버리고 ack"
        ok("턴 끝: done → status done · 답 메시지 = delta 합 · messages?after · session_ref 저장 · 끝난 턴 이벤트 버림")

        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "두 번째", "client_turn_id": "t-2"})
        assert r.status_code == 201
        tid2 = r.json()["turn_id"]
        st = pc.wait(lambda m: m["type"] == "turn.start")
        assert st["turn_id"] == tid2 and st["cli_session_ref"] == "fake-ref-1", "재개용 CLI 세션 ID 를 싣는다"
        r = h.post(f"/api/chat/sessions/{sid}/stop")
        assert r.status_code == 200 and r.json() == {"turn_id": tid2, "status": "stopped"}
        assert pc.wait(lambda m: m["type"] == "turn.stop" and m["turn_id"] == tid2)
        pc.event(tid2, 1, "delta", {"text": "멈춘 뒤"})
        assert pc.ack(tid2) == 1
        assert pc.wait(lambda m: m["type"] == "turn.stop" and m["turn_id"] == tid2), "끝난 턴 이벤트 = turn.stop 다시(중지 때 PC 가 끊겼을 수 있다)"
        pc.event(tid2, 2, "delta", {"text": "또"})
        assert pc.ack(tid2) == 2 and pc.wait(lambda m: m["type"] == "turn.stop" and m["turn_id"] == tid2, 0.5) is None, "연결당 한 번"
        ev = rows("SELECT seq, kind, data FROM chat_events WHERE turn_id=%s ORDER BY seq", (tid2,))
        assert [(e["kind"], e["data"]) for e in ev] == [("error", {"code": "STOPPED"})], ev
        assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid2,))[0]["status"] == "stopped"
        assert h.post(f"/api/chat/sessions/{sid}/stop").json() == {"turn_id": None, "status": None}
        ok("중지: 서버에서 바로 stopped + error STOPPED · PC 에 turn.stop · 뒤늦은 이벤트 버림(ack) + turn.stop 한 번 더 · 실행 중 없음 = null")

        old = webchat.EVENTS_PER_TURN
        webchat.EVENTS_PER_TURN = 2
        try:
            tid3 = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "한도", "client_turn_id": "t-3"}).json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            pc.event(tid3, 1, "delta", {"text": "a"})
            pc.event(tid3, 2, "delta", {"text": "b"})
            pc.event(tid3, 3, "delta", {"text": "c"})
            assert pc.wait(lambda m: m["type"] == "turn.stop" and m["turn_id"] == tid3), "한도 = PC 에 turn.stop"
            t = rows("SELECT status FROM chat_turns WHERE id=%s", (tid3,))[0]
            ev = rows("SELECT kind, data FROM chat_events WHERE turn_id=%s ORDER BY seq", (tid3,))
            assert t["status"] == "failed" and ev[-1]["data"] == {"code": "TURN-LIMIT"} and len(ev) == 3, ev
        finally:
            webchat.EVENTS_PER_TURN = old
        ok("한도: 턴당 이벤트 수 초과 = failed(TURN-LIMIT) + turn.stop")

        old = webchat.TURN_IDLE_SECONDS
        webchat.TURN_IDLE_SECONDS = 1
        try:
            tid4 = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "조용", "client_turn_id": "t-4"}).json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            time.sleep(1.6)
            r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "다음", "client_turn_id": "t-5"})
            assert r.status_code == 201, r.text
            assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid4,))[0]["status"] == "failed"
            assert rows("SELECT data FROM chat_events WHERE turn_id=%s ORDER BY seq DESC LIMIT 1", (tid4,))[0]["data"] == {"code": "TURN-TIMEOUT"}
            tid5 = r.json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            pc.event(tid5, 1, "done", {})
            assert pc.ack(tid5) == 1
        finally:
            webchat.TURN_IDLE_SECONDS = old
        ok("유휴 턴: 이벤트 없이 기준 지난 running = 다음 입력 때 failed(TURN-TIMEOUT) — 영구 TURN-BUSY 없음")

        pc.send({"type": "event", "turn_id": tid, "seq": 9, "kind": "delta", "data": {"text": "x" * (webchat.WS_MESSAGE_MAX + 10)}})
        assert pc.wait_closed() == 1009, pc.closed
        ok("WS 메시지 64KB 초과 = close 1009")
    return tid


def test_foreign(srv, ub, tok_b1, sid_a, tid_a):
    pc = PC(srv, tok_b1)   # 다른 사용자 장치가 남의 턴에 이벤트를 보낸다
    pc.event(tid_a, 6, "delta", {"text": "남의 턴"})
    assert pc.ack(tid_a, 1.0) is None, "남의 턴 = ack 없음"
    pc.send({"type": "session_ref", "session_id": sid_a, "cli_session_ref": "evil"})
    time.sleep(0.3)
    assert rows("SELECT count(*) AS n FROM chat_events WHERE turn_id=%s AND seq=6", (tid_a,))[0]["n"] == 0
    assert rows("SELECT cli_session_ref FROM chat_sessions WHERE id=%s", (sid_a,))[0]["cli_session_ref"] == "fake-ref-1"
    pc.close()
    sse = SSE(srv, ub, sid_a)
    assert sse.status == 404, "남의 세션 SSE = 404"
    sse.close()
    ok("남의 턴·세션: 다른 사용자 장치 이벤트 저장·ack 없음 · session_ref 거절 · 남의 SSE 404")


def test_review(srv):
    """PR #45 리뷰 반영 — 재생 상한·누계 열·pc 거름·세션 닫기 = 턴 끝·GET 유휴 정리·동시 중지+수신·수신 예외에도 연결 유지."""
    old_rate = webchat.TURNS_PER_MINUTE
    webchat.TURNS_PER_MINUTE = 1000   # 이 절은 턴을 많이 만든다 — 분당 한도는 test_rate 가 본다
    try:
        _review(srv)
    finally:
        webchat.TURNS_PER_MINUTE = old_rate


def _review(srv):
    u = db.user_by_email("wc-rev@example.com")["id"]
    d1, d2 = imports.device_connect(u, "rev pc1"), imports.device_connect(u, "rev pc2")
    pc = PC(srv, d1["token"])
    time.sleep(0.2)
    with web(srv, u) as h:
        for _ in range(100):
            caps = h.get("/api/chat/capabilities").json()["devices"]
            if any(d["device_id"] == d1["device"]["id"] and d["capabilities"] for d in caps):
                break
            time.sleep(0.05)
        assert any(d["device_id"] == d1["device"]["id"] for d in caps), caps
        sr = h.post("/api/chat/sessions", json={"operation": "new", "device_id": d1["device"]["id"], "provider": "fake", "model": None, "client_session_id": "review-session"})
        assert sr.status_code == 201, sr.text
        sid = sr.json()["session_id"]
        tids = []
        for i in range(4):
            tid = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": f"q{i}", "client_turn_id": f"rv-{i}"}).json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            pc.event(tid, 1, "delta", {"text": "가나"})
            pc.event(tid, 2, "done", {})
            assert pc.ack(tid) == 1 and pc.ack(tid) == 2
            tids.append(tid)
        t = rows("SELECT n_events, n_bytes FROM chat_turns WHERE id=%s", (tids[0],))[0]
        assert (t["n_events"], t["n_bytes"]) == (2, webchat._jbytes({"text": "가나"}) + webchat._jbytes({})), t
        ok("누계 열: n_events·n_bytes = 저장한 이벤트 수·압축 JSON 바이트(_jbytes) — 매번 세지 않는다")

        old = webchat.REPLAY_TURNS
        webchat.REPLAY_TURNS = 2
        try:
            sse = SSE(srv, u, sid)
            e, _ = sse.until("done")
            e2, _ = sse.until("done")
            evs = [x for x in e + e2 if x["event"] != "pc"]
            assert evs[0]["event"] == "trimmed" and evs[0]["data"]["first_turn_id"] == tids[2] and "id" not in evs[0], evs[0]
            assert [x["data"]["turn_id"] for x in evs if x["event"] == "turn"] == tids[2:], "최근 2턴만"
            sse.close()
            sse = SSE(srv, u, sid, last_id=f"{tids[0]}:2")   # 커서가 상한 밖 — 최근 N턴만(앞은 messages API)
            e, _ = sse.until("trimmed")
            assert e[-1]["data"]["first_turn_id"] == tids[2]
            sse.close()
        finally:
            webchat.REPLAY_TURNS = old
        ok("재생 상한: 최근 REPLAY_TURNS 턴(커서가 상한 밖이어도) · 앞부분 생략 = trimmed(id 없음) · 이벤트 한 쿼리")

        sse = SSE(srv, u, sid)
        assert sse.next()["event"] == "pc"
        pc2 = PC(srv, d2["token"])   # 다른 장치가 붙고 끊김 — 이 세션 SSE 엔 pc 가 오지 않는다
        time.sleep(0.2)
        pc2.close()
        time.sleep(0.3)
        got = []
        while True:
            x = sse.next(0.5)
            if x in (None, "timeout"):
                break
            got.append(x)
        assert not [x for x in got if x["event"] == "pc"], got
        sse.close()
        ok("pc 이벤트: 그 세션 장치(device_id)만 — 다른 PC 연결·끊김은 거른다")

        old = webchat.TURN_IDLE_SECONDS
        webchat.TURN_IDLE_SECONDS = 1
        try:
            tid = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "조용", "client_turn_id": "rv-idle"}).json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            time.sleep(1.6)
            assert h.get("/api/chat/sessions").status_code == 200
            assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] == "failed", "세션 목록 조회 때 유휴 정리"
            tid = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "조용2", "client_turn_id": "rv-idle2"}).json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            time.sleep(1.6)
            sse = SSE(srv, u, sid, last_id=f"{tid}:0")
            e, last = sse.until("error")
            assert last["data"]["data"] == {"code": "TURN-TIMEOUT"}, "SSE 연결 때 유휴 정리 — 재생에 들어간다"
            sse.close()
        finally:
            webchat.TURN_IDLE_SECONDS = old
        ok("유휴 정리: 세션 목록·SSE 연결 때도 돈다(화면은 실행 중이면 보내기를 막는다)")

        errs = []
        for i in range(6):   # 답 나오는 중 중지 — 잠금 순서(세션 → 턴)가 같아 교착·500 없음
            tid = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "중지 경합", "client_turn_id": f"rv-race-{i}"}).json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            go = threading.Event()

            def flood():
                go.wait()
                for k in range(1, 30):
                    pc.event(tid, k, "delta", {"text": "x"})

            th = threading.Thread(target=flood)
            th.start()
            go.set()
            time.sleep(0.01 * i)
            r = h.post(f"/api/chat/sessions/{sid}/stop")
            th.join()
            if r.status_code != 200:
                errs.append(r.status_code)
            time.sleep(0.2)
            assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] == "stopped"
        assert errs == [] and pc.closed is None, (errs, pc.closed)
        ok("동시 중지 + 수신 6회: 중지 200 · 턴 stopped · WS 유지(교착 없음)")

        tid = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "닫힘", "client_turn_id": "rv-close"}).json()["turn_id"]
        pc.wait(lambda m: m["type"] == "turn.start")
        sse = SSE(srv, u, sid, last_id=f"{tid}:0")
        assert sse.next()["event"] == "pc"
        s2 = h.post("/api/chat/sessions", json={"device_id": d2["device"]["id"]}).json()["session_id"]
        e, last = sse.until("error")
        assert last["data"]["turn_id"] == tid and last["data"]["data"] == {"code": "SESSION-CLOSED"}, ("닫으며 끝낸 턴을 SSE 에", e)
        sse.close()
        assert s2 != sid and rows("SELECT status FROM chat_sessions WHERE id=%s", (sid,))[0]["status"] == "closed"
        assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] == "failed"
        assert rows("SELECT data FROM chat_events WHERE turn_id=%s ORDER BY seq DESC LIMIT 1", (tid,))[0]["data"] == {"code": "SESSION-CLOSED"}
        ok("세션 닫기(다른 장치 선택) = 실행 중 턴 failed(SESSION-CLOSED) · 그 끝 이벤트를 보던 SSE 에 보냄")
    pc.close()
    for _ in range(100):
        if not webchat.hub.connected(u, d1["device"]["id"]) and not webchat.hub.connected(u, d2["device"]["id"]):
            break
        time.sleep(0.05)
    assert not webchat.hub.connected(u, d1["device"]["id"]) and not webchat.hub.connected(u, d2["device"]["id"]), "이전 WS detach 전 오류 주입 금지"

    # 수신 예외 → 서버가 1011 로 닫음 → 실제 PC 에이전트(agent.chat)가 다시 붙어 미확인 이벤트를 재전송 → 턴 done, 출력 손실 없음
    orig = webchat.ingest
    calls = {"n": 0}
    ingest_trace = []

    def boom(dev, *a, **k):
        if dev["id"] != d2["device"]["id"]:   # 이전 장치의 늦은 이벤트가 재연결 시험을 소비하지 않게 한다
            return orig(dev, *a, **k)
        calls["n"] += 1
        ingest_trace.append((dev["id"], a[0] if len(a) > 0 else None, a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else None))
        if calls["n"] == 2:
            raise RuntimeError("일시 장애")
        return orig(dev, *a, **k)

    stopping = threading.Event()
    agent_log = []
    agent = agent_chat.ChatAgent(srv.ws, d2["token"], agent_chat.FakeProvider(step=0.05), agent_version="t", stopping=stopping,
                                 backoff=wsclient.Backoff(base=0.1, cap=0.3, jitter=0), recv_tick=0.05, coalesce=0.0, log=agent_log.append)
    th = threading.Thread(target=agent.run, daemon=True)
    th.start()
    webchat.ingest = boom
    try:
        with web(srv, u) as h:
            for _ in range(50):
                if h.get("/api/chat/sessions").json()["sessions"][0]["connected"]:
                    break
                time.sleep(0.1)
            sr = h.post("/api/chat/sessions", json={"operation": "new", "device_id": d2["device"]["id"], "provider": "fake", "model": None, "client_session_id": "review-agent-session"})
            assert sr.status_code == 201, sr.text
            s2 = sr.json()["session_id"]
            tid = h.post(f"/api/chat/sessions/{s2}/turns", json={"text": "안녕", "client_turn_id": "rv-exc"}).json()["turn_id"]
            for _ in range(100):
                if rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] != "running":
                    break
                time.sleep(0.1)
            assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] == "done"
            body = [m["body"] for m in h.get(f"/api/chat/sessions/{s2}/messages").json()["messages"] if m["turn_id"] == tid and m["role"] == "assistant"]
            assert body == ["가짜 답이에요. 받은 글은 2자예요. 끝."], body
            seqs = [r["seq"] for r in rows("SELECT seq FROM chat_events WHERE turn_id=%s ORDER BY seq", (tid,))]
            assert seqs == list(range(1, len(seqs) + 1)) and calls["n"] >= 3 and agent.connects >= 2, (seqs, calls, ingest_trace, agent.connects, agent_log)
            assert all(record[0] == d2["device"]["id"] for record in ingest_trace), ingest_trace
    finally:
        webchat.ingest = orig
        stopping.set()
        th.join(5)
    ok("수신 예외(DB 일시 장애 등): 서버 1011 로 닫음 → PC 에이전트 재연결·재전송 → 턴 done · 출력 손실 없음 · seq 연속")


def test_rate(srv):
    u = db.user_by_email("wc-rate@example.com")["id"]
    device = imports.device_connect(u, "rate pc")
    tok = device["token"]
    pc = PC(srv, tok)
    time.sleep(0.2)
    with web(srv, u) as h:
        sid = h.post("/api/chat/sessions", json={"operation": "new", "device_id": device["device"]["id"], "provider": "fake", "model": None, "client_session_id": "rate-session"}).json()["session_id"]
        for i in range(webchat.TURNS_PER_MINUTE):
            r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "r", "client_turn_id": f"r-{i}"})
            assert r.status_code == 201, (i, r.text)
            tid = r.json()["turn_id"]
            pc.wait(lambda m: m["type"] == "turn.start")
            pc.event(tid, 1, "done", {})
            assert pc.ack(tid) == 1
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "r", "client_turn_id": "r-x"})
        assert r.status_code == 429 and r.json()["code"] == "RATE-LIMIT", r.text
    pc.close()
    ok(f"한도: 턴 분당 {webchat.TURNS_PER_MINUTE} — 넘으면 429 RATE-LIMIT")


def test_revoke(srv, ua, tok_a, dev_a, sid):
    old = webchat.PING_SECONDS
    webchat.PING_SECONDS = 0.3
    try:
        pc = PC(srv, tok_a)
        assert pc.wait(lambda m: m["type"] == "ping", 3), "ping"
        imports.device_revoke(ua, dev_a)
        assert pc.wait_closed(3) == 4001, ("철회 = 4001", pc.closed)
    finally:
        webchat.PING_SECONDS = old
    with web(srv, ua) as h:
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "철회 뒤", "client_turn_id": "after-revoke"})
        assert r.status_code == 409 and r.json()["code"] == "DEVICE-GONE", r.text
        assert rows("SELECT status FROM chat_sessions WHERE id=%s", (sid,))[0]["status"] == "closed"
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "철회 뒤", "client_turn_id": "after-revoke-2"})
        assert r.json()["code"] == "SESSION-CLOSED"
        r = h.post("/api/chat/sessions", json={})
        assert r.status_code == 409 and r.json()["code"] == "NO-DEVICE"
    ok("장치 철회: 연결 중 WS = 재확인 때 4001 · 새 턴 409 DEVICE-GONE(세션 닫힘) · 장치 없음 409 NO-DEVICE")


def test_switch_runtime(srv, ub, tok_b2, sid_b):
    pc = PC(srv, tok_b2)
    old = webchat.HEARTBEAT_SECONDS
    webchat.HEARTBEAT_SECONDS = 0.5
    try:
        sse = SSE(srv, ub, sid_b)
        assert sse.next()["event"] == "pc"
        switch(False)
        pc.send({"type": "pong"})
        assert pc.wait_closed(3) == 1013, pc.closed
        rest = []
        while True:   # 장치 끊김 알림(pc)이 끝보다 먼저 올 수도, 안 올 수도 있다(heartbeat 판정과 경합) — 끝은 반드시
            e = sse.next(5)
            assert e != "timeout", "꺼지면 SSE 도 끝난다"
            if e is None:
                break
            rest.append(e)
        assert all(x["event"] == "pc" and x["data"]["connected"] is False for x in rest), rest
        sse.close()
    finally:
        webchat.HEARTBEAT_SECONDS = old
        switch(True)
    ok("실행 중 스위치 꺼짐: 장치 WS close 1013 · SSE 끝")


def test_purge(ua_del):
    u = ua_del
    dev = imports.device_connect(u, "purge pc")["device"]["id"]
    sid_old, sid_new = webchat._id("cs"), webchat._id("cs")
    with db.tx() as c:
        c.execute("INSERT INTO chat_sessions (id,user_id,device_id,status,created_at) VALUES (%s,%s,%s,'closed', now() - interval '31 days')",
                  (sid_old, u, dev))
        c.execute("INSERT INTO chat_sessions (id,user_id,device_id) VALUES (%s,%s,%s)", (sid_new, u, dev))
        for sid, tid, age, st in ((sid_old, webchat._id("ct"), 31, "done"), (sid_new, webchat._id("ct"), 31, "done"),
                                  (sid_new, webchat._id("ct"), 1, "done"), (sid_new, webchat._id("ct"), 40, "running")):
            end = "NULL" if st == "running" else "now()"
            c.execute(f"INSERT INTO chat_turns (id,session_id,client_turn_id,status,created_at,ended_at) VALUES "
                      f"(%s,%s,%s,%s, now() - make_interval(days => %s), {end})", (tid, sid, tid[-8:], st, age))
            c.execute("INSERT INTO chat_messages (id,session_id,turn_id,role,body,created_at) VALUES (%s,%s,%s,'user','x', now() - make_interval(days => %s))",
                      (webchat._id("cm"), sid, tid, age))
            c.execute("INSERT INTO chat_events (turn_id,seq,kind,data,created_at) VALUES (%s,1,'delta','{\"text\":\"x\"}', now() - make_interval(days => %s))",
                      (tid, age))
    n = webchat.purge()
    left = rows("SELECT t.status, (t.created_at > now() - interval '30 days') AS young FROM chat_turns t JOIN chat_sessions s ON s.id=t.session_id "
                "WHERE s.user_id=%s ORDER BY t.created_at", (u,))
    assert [(r["status"], r["young"]) for r in left] == [("done", True)], ("30일 넘은 running 도 failed 로 끝낸 뒤 삭제", left)
    assert rows("SELECT id FROM chat_sessions WHERE user_id=%s", (u,)) == [{"id": sid_new}], "빈 30일+ 세션 삭제, 새 세션 유지"
    assert rows("SELECT count(*) AS n FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id WHERE s.user_id=%s", (u,))[0]["n"] == 1
    assert n >= 4, n   # 턴 3(cascade 로 메시지·이벤트) + 빈 세션 1
    src = (HERE / "main.py").read_text(encoding="utf-8")
    body = src[src.index("async def purge_once"):src.index("async def trash_purge_round")]
    assert "webchat.purge" in body, "purge_once 회차에 얹었다"
    ok("30일 삭제: 생성일 30일 지난 턴·메시지·이벤트·빈 세션 삭제 · 30일 넘은 running = failed 뒤 삭제 · 새 것 유지 · purge_once 경로")
    db.user_delete(u)
    assert rows("SELECT count(*) AS n FROM chat_sessions WHERE id=ANY(%s)", ([sid_old, sid_new],))[0]["n"] == 0
    assert rows("SELECT count(*) AS n FROM chat_messages WHERE session_id=ANY(%s)", ([sid_old, sid_new],))[0]["n"] == 0
    ok("계정 삭제: chat_sessions → 턴·이벤트·메시지 cascade")


def main_():
    db.init_schema()
    db.init_schema()   # 멱등
    cleanup()
    with db.tx() as c:   # PR 1 첫 판 표(누계 열 없음) → init_schema 가 열을 더한다
        c.execute("ALTER TABLE chat_turns DROP COLUMN n_events, DROP COLUMN n_bytes")
    db.init_schema()
    cols = {r["column_name"]: r["column_default"] for r in rows(
        "SELECT column_name, column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='chat_turns'")}
    assert cols.get("n_events") == "0" and cols.get("n_bytes") == "0", cols
    ok("옛 표 업그레이드: chat_turns 누계 열이 없으면 init_schema 가 ADD COLUMN IF NOT EXISTS(기본 0)")
    test_static()
    ua = db.user_by_email(EMAILS[0])["id"]
    ub = db.user_by_email(EMAILS[1])["id"]
    a = imports.device_connect(ua, "a pc")
    tok_a, dev_a = a["token"], a["device"]["id"]
    test_chat_session_migration(ua, dev_a)
    test_consent_challenge(ua, ub, tok_a, dev_a)
    r = imports.device_connect(ua, "a old pc")
    imports.device_revoke(ua, r["device"]["id"])
    revoked = r["token"]
    b1, b2 = imports.device_connect(ub, "b pc1"), imports.device_connect(ub, "b pc2")
    with Server() as srv:
        main.site.dev, main.site.dev_user = False, ""
        test_switch_off(srv, ua, tok_a)
        test_gate(srv, ua)
        test_ws_auth(srv, tok_a, revoked)
        test_v2_capabilities(srv, ua, tok_a, dev_a)
        test_fake_not_advertised_outside_dev()
        test_consent_fail_closed(srv, ua, tok_a, dev_a)
        test_grant_fail_closed(ua, ub, dev_a)
        test_wall_clock_expiry_after_row_lock_wait(ua, dev_a)
        test_unapproved_keeps_active(srv, ua, tok_a, dev_a)
        test_consent_routes(srv, ua, ub, tok_a, dev_a)
        test_consent_result(srv, ua, ub, tok_a, dev_a)
        test_consent_bind_empty_device(srv, ua, ub)
        test_standing_permit(srv)
        test_ai_links(srv)
        sid_a, sid_b = test_sessions(srv, ua, ub, tok_a, dev_a, b2["device"]["id"])
        tid_a = test_turns(srv, ua, tok_a, sid_a)
        test_foreign(srv, ub, b1["token"], sid_a, tid_a)
        test_review(srv)
        test_rate(srv)
        test_switch_runtime(srv, ub, b2["token"], sid_b)
        test_revoke(srv, ua, tok_a, dev_a, sid_a)
    test_purge(db.user_by_email("wc-del@example.com")["id"])
    cleanup()
    switch(False)
    print(f"1..{N} — 웹 「대화」 전송 골격 시험 통과", flush=True)


if __name__ == "__main__":
    main_()
    db.close()
