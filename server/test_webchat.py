"""웹 「대화」 전송 골격 시험(2026-11-04 PR 1) — 실제 uvicorn(스레드) + 장치 WS(agent/wsclient) + SSE(http.client) + 합성 PG.

실행: DATABASE_URL=postgresql://localhost/crm_test_webchat python3 server/test_webchat.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

다루는 것: 스위치 꺼짐 503(API·SSE·WS) · 세션(장치 자동·여러 대·없음) · 턴 멱등·TURN-BUSY·DEVICE-OFFLINE · (turn_id,seq) 중복 무시·빈 칸
· 누적 ack · SSE 재생·Last-Event-ID 재개·사용자당 1 · WS 인증(무토큰·틀림·철회·다른 사용자 턴 거절) · 중지 · 한도(글자·분당·이벤트·WS 64KB)
· 유휴 턴 TURN-TIMEOUT · 30일 삭제 · 계정 삭제 cascade · 응답에 남의 데이터 없음.
"""
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import webchat  # noqa: E402
from agent import chat as agent_chat  # noqa: E402
from agent import wsclient  # noqa: E402

EMAILS = ("wc-a@example.com", "wc-b@example.com", "wc-rate@example.com", "wc-del@example.com", "wc-rev@example.com")
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

    def __init__(self, srv, token):
        self.ws = wsclient.connect(srv.ws, {"Authorization": "Bearer " + token}, timeout=5)
        self.inbox, self.closed = [], None
        self.cv = threading.Condition()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()
        self.send({"type": "hello", "agent_version": "test", "providers": ["fake"]})

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
                  h.post("/api/chat/sessions/cs_x/turns", json={"text": "a", "client_turn_id": "c1"})):
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


def test_sessions(srv, ua, ub, dev_b2):
    with web(srv, ua) as h:
        r = h.post("/api/chat/sessions", json={})
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["status"] == "active" and s["connected"] is False and s["session_id"].startswith("cs_")
        assert h.post("/api/chat/sessions", json={}).json()["session_id"] == s["session_id"], "활성 세션 1 — 같은 세션"
        lst = h.get("/api/chat/sessions").json()["sessions"]
        assert [x["session_id"] for x in lst] == [s["session_id"]]
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
        r = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "안녕 PC", "client_turn_id": "t-1"})
        assert r.status_code == 201 and r.json()["created"] is True, r.text
        tid = r.json()["turn_id"]
        st = pc.wait(lambda m: m["type"] == "turn.start")
        assert st and st["turn_id"] == tid and st["text"] == "안녕 PC" and st["session_id"] == sid and "cli_session_ref" not in st
        r2 = h.post(f"/api/chat/sessions/{sid}/turns", json={"text": "안녕 PC", "client_turn_id": "t-1"})
        assert r2.status_code == 200 and r2.json() == {"turn_id": tid, "status": "running", "created": False}, r2.text
        assert pc.wait(lambda m: m["type"] == "turn.start", 0.5) is None, "멱등 — 다시 보내지 않는다"
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
        sid = h.post("/api/chat/sessions", json={"device_id": d1["device"]["id"]}).json()["session_id"]
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

    # 수신 예외 → 서버가 1011 로 닫음 → 실제 PC 에이전트(agent.chat)가 다시 붙어 미확인 이벤트를 재전송 → 턴 done, 출력 손실 없음
    orig = webchat.ingest
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("일시 장애")
        return orig(*a, **k)

    stopping = threading.Event()
    agent = agent_chat.ChatAgent(srv.ws, d2["token"], agent_chat.FakeProvider(step=0.05), agent_version="t", stopping=stopping,
                                 backoff=wsclient.Backoff(base=0.1, cap=0.3, jitter=0), recv_tick=0.05, coalesce=0.0)
    th = threading.Thread(target=agent.run, daemon=True)
    th.start()
    webchat.ingest = boom
    try:
        with web(srv, u) as h:
            for _ in range(50):
                if h.get("/api/chat/sessions").json()["sessions"][0]["connected"]:
                    break
                time.sleep(0.1)
            tid = h.post(f"/api/chat/sessions/{s2}/turns", json={"text": "안녕", "client_turn_id": "rv-exc"}).json()["turn_id"]
            for _ in range(100):
                if rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] != "running":
                    break
                time.sleep(0.1)
            assert rows("SELECT status FROM chat_turns WHERE id=%s", (tid,))[0]["status"] == "done"
            body = [m["body"] for m in h.get(f"/api/chat/sessions/{s2}/messages").json()["messages"] if m["turn_id"] == tid and m["role"] == "assistant"]
            assert body == ["가짜 답이에요. 받은 글은 2자예요. 끝."], body
            seqs = [r["seq"] for r in rows("SELECT seq FROM chat_events WHERE turn_id=%s ORDER BY seq", (tid,))]
            assert seqs == list(range(1, len(seqs) + 1)) and calls["n"] >= 3 and agent.connects >= 2, (seqs, calls, agent.connects)
    finally:
        webchat.ingest = orig
        stopping.set()
        th.join(5)
    ok("수신 예외(DB 일시 장애 등): 서버 1011 로 닫음 → PC 에이전트 재연결·재전송 → 턴 done · 출력 손실 없음 · seq 연속")


def test_rate(srv):
    u = db.user_by_email("wc-rate@example.com")["id"]
    tok = imports.device_connect(u, "rate pc")["token"]
    pc = PC(srv, tok)
    time.sleep(0.2)
    with web(srv, u) as h:
        sid = h.post("/api/chat/sessions", json={}).json()["session_id"]
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
    r = imports.device_connect(ua, "a old pc")
    imports.device_revoke(ua, r["device"]["id"])
    revoked = r["token"]
    b1, b2 = imports.device_connect(ub, "b pc1"), imports.device_connect(ub, "b pc2")
    with Server() as srv:
        main.site.dev, main.site.dev_user = False, ""
        test_switch_off(srv, ua, tok_a)
        test_gate(srv, ua)
        test_ws_auth(srv, tok_a, revoked)
        sid_a, sid_b = test_sessions(srv, ua, ub, b2["device"]["id"])
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
