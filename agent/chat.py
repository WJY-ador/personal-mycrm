"""웹 「대화」 PC 쪽 — 서버 WebSocket 하나를 붙들고, 받은 턴을 공급자(구독 CLI 어댑터)로 실행해 출력 조각을 올려 보낸다.

계약(서버 server/webchat.py 와 같은 값, notes 구현계획 §2):
- 연결: wss://<서버>/api/device/chat/ws · Authorization: Bearer <장치 토큰>. 장치당 1연결(새 연결이 옛 연결을 대체).
- 서버→PC turn.start{session_id, turn_id, text, cli_session_ref?, approval_outcomes?} · turn.stop{turn_id} · ack{turn_id, seq} · ping
- PC→서버 hello{agent_version, providers[], ai_links?} · event{turn_id, seq, kind, data} · session_ref{session_id, cli_session_ref} · pong
  · ai_links = 이 PC 의 AI 연결 {claude|codex: linked|signed_out|off|missing}(명세 2026-11-13 1.3, 장치가 보고한 값).
    서버는 linked 를 허용으로 세운다. 상태가 바뀌면 같은 연결에서 hello 를 다시 보낸다.
- kind = delta{text} · tool_call{name, input?} · tool_result{name, ok, summary?} · done{} · error{code}. 중지 = error{code:"STOPPED"}.
- seq 는 턴 안에서 1부터. delta 는 최대 COALESCE_SEC(0.5초) 묶음. ack(누적) 전 이벤트만 턴당 BUFFER_MAX(256KB) 보유,
  재연결 때 그대로 다시 보낸다(서버가 (turn_id, seq) 중복을 무시). 버퍼가 차면 공급자를 멈추고 error{code:"BUFFER-LIMIT"} 로 끝낸다.
- 턴 자동 재실행 금지 — 연결이 끊겨도 실행 중 턴은 계속 돌고, 출력만 재전송한다.
- 공급자 어댑터: start_turn(text, cli_session_ref, approval_outcomes?) → (kind, data) 이터레이터 · stop(). 서버 생성 approval_outcomes 는
  사용자 원문과 분리된 내부 context 로만 전달한다. kind "session_ref" 는 이벤트가 아니라
  session_ref 메시지로 보낸다(CLI 세션 ID 는 PC 가 보유 — 재개용으로만 서버에 둔다).
- 메시지 하나 ≤ WS_MESSAGE_MAX(64KB): delta 는 쪼개 보내고, 그 밖 이벤트는 짧은 값만 남긴 data + truncated:true 로 줄인다.
- SILENCE_MAX(서버 ping 2번) 동안 아무것도 못 받으면 반쯤 열린 연결로 보고 닫고 다시 붙는다.
- 토큰: 공급 함수(키 저장소를 다시 읽는다). 핸드셰이크 401·403 이나 close 4001 이면 한 번 다시 읽어 바뀌었으면 새 토큰으로,
  같으면 멈춘다(rotate·재발급 뒤 상주가 죽지 않게).
- 로그 = 코드만(본문·토큰·주소 없음).
PR 1 은 FakeProvider(정해진 대본)만. ClaudeProvider(실 CLI)는 PR 2.
"""
from __future__ import annotations

import json
import queue
import re
import secrets
import socket
import threading
import time
from collections import OrderedDict

from . import wsclient
from .chat_providers import CliSessionRefStore, ProviderRegistry, ProviderUnavailable
from .chat_approval_context import normalize_approval_outcomes

WS_PATH = "/api/device/chat/ws"
COALESCE_SEC = 0.5
BUFFER_MAX = 256 * 1024
WS_MESSAGE_MAX = 64 * 1024     # 서버 server/webchat.py WS_MESSAGE_MAX 와 같은 값 — 넘는 메시지는 서버가 1009 로 닫는다(재전송 무한 반복)
PING_SECONDS = 25              # 서버 server/webchat.py PING_SECONDS 와 같은 값
SILENCE_MAX = 2 * PING_SECONDS # 이만큼 아무것도 못 받으면 반쯤 열린 연결로 보고 닫은 뒤 다시 붙는다
RECV_TICK = 1.0
SEEN_MAX = 1000
KINDS = ("delta", "tool_call", "tool_result", "done", "error")
TERMINAL = ("done", "error")
# hello 에 AI 연결 상태를 싣는 필드 이름(계약, 서버 S 정본 2026-11-13).
HELLO_AI_KEY = "ai_links"
# 이 PC 에서 그 공급자가 linked 가 아니라 턴을 거절할 때의 오류 코드.
AI_REFUSALS = {"off": "AI-OFF", "signed_out": "AI-SIGNED-OUT", "missing": "AI-MISSING"}


def ws_url(server_url: str) -> str:
    s = server_url.rstrip("/")
    if s.startswith("https://"):
        return "wss://" + s[len("https://"):] + WS_PATH
    if s.startswith("http://"):
        return "ws://" + s[len("http://"):] + WS_PATH
    raise ValueError("server_url")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _size(turn_id: str, kind: str, data: dict) -> int:
    return len(_dumps({"type": "event", "turn_id": turn_id, "seq": 999999999, "kind": kind, "data": data}).encode("utf-8"))


def fit_event(turn_id: str, kind: str, data: dict, limit: int = WS_MESSAGE_MAX) -> list:
    """메시지 하나가 limit 바이트를 넘지 않게 — delta 는 글을 쪼갠 data 목록, 그 밖은 줄인 data 하나(truncated:true)."""
    if _size(turn_id, kind, data) <= limit:
        return [data]
    if kind == "delta":
        text = data.get("text") if isinstance(data.get("text"), str) else ""
        n = max(1, (limit - 512) // 6)   # 글자 하나 최악 6바이트(JSON \uXXXX) — 조각마다 상한 안
        return [{"text": text[i:i + n]} for i in range(0, len(text), n)] or [{"text": ""}]
    small = {}
    for k, v in data.items():
        if v is None or isinstance(v, (bool, int, float)):
            small[k] = v
        elif isinstance(v, str):
            small[k] = v[:2000]
    small["truncated"] = True
    return [small] if _size(turn_id, kind, small) <= limit else [{"truncated": True}]


class FakeProvider:
    """시험·측정용 공급자 — 받은 글 길이만 쓰는 정해진 대본을 시간차로 낸다(모델 호출 없음)."""

    name = "fake"

    def __init__(self, step: float = 0.2, script=None):
        self.step = step
        self.script = script
        self._stop = threading.Event()
        self.turns = 0
        self.last_turn_text = None
        self.last_approval_outcomes = ()

    def _default(self, text: str):
        n = len(text)
        return [("delta", {"text": "가짜 답이에요. "}),
                ("delta", {"text": f"받은 글은 {n}자예요. "}),
                ("tool_call", {"name": "find", "input": {"q": "fake"}}),
                ("tool_result", {"name": "find", "ok": True, "summary": "가짜 도구 결과"}),
                ("delta", {"text": "끝."}),
                ("done", {})]

    def start_turn(self, text: str, cli_session_ref: str | None = None, *, approval_outcomes=()):
        self._stop.clear()
        self.turns += 1
        self.last_turn_text = text
        self.last_approval_outcomes = tuple(approval_outcomes)
        if not cli_session_ref:
            yield "session_ref", {"cli_session_ref": f"fake-{int(time.time())}-{self.turns}"}
        for kind, data in (self.script(text) if callable(self.script) else self.script or self._default(text)):
            if self._stop.wait(self.step):
                yield "error", {"code": "STOPPED"}
                return
            yield kind, data

    def stop(self) -> None:
        self._stop.set()


class TurnBuffer:
    """한 턴의 미확인(ack 전) 이벤트 — seq 순. 상한 BUFFER_MAX 바이트."""

    def __init__(self, turn_id: str, limit: int = BUFFER_MAX):
        self.turn_id, self.limit = turn_id, limit
        self.items: OrderedDict = OrderedDict()   # seq → (메시지 글, 바이트)
        self.bytes = 0
        self.seq = 0
        self.acked = 0
        self.ended = False
        self.lock = threading.Lock()

    def add(self, kind: str, data: dict, force: bool = False):
        """다음 seq 로 넣고 보낼 글을 돌려준다. 상한을 넘으면 None(force = 끝 이벤트는 상한을 넘어도 넣는다)."""
        with self.lock:
            msg = _dumps({"type": "event", "turn_id": self.turn_id, "seq": self.seq + 1, "kind": kind, "data": data})
            size = len(msg.encode("utf-8"))
            if not force and self.bytes + size > self.limit:
                return None
            self.seq += 1
            self.items[self.seq] = (msg, size)
            self.bytes += size
            if kind in TERMINAL:
                self.ended = True
            return msg

    def ack(self, seq: int) -> None:
        with self.lock:
            self.acked = max(self.acked, seq)
            for s in [s for s in self.items if s <= seq]:
                self.bytes -= self.items.pop(s)[1]

    def pending(self) -> list:
        with self.lock:
            return [m for m, _ in self.items.values()]

    def done(self) -> bool:
        with self.lock:
            return self.ended and not self.items


class ChatAgent:
    """연결 관리 · 턴 실행. run() 은 stopping 이 설 때까지(또는 인증 거절) 돈다. 반환 = 멈춘 이유(signal·auth·switch-off 아님 — 재시도)."""

    def __init__(self, url: str, token, provider=None, *, registry=None, ref_store=None, agent_version: str = "", connect=wsclient.connect,
                 backoff: wsclient.Backoff | None = None, stopping: threading.Event | None = None, log=None,
                 coalesce: float = COALESCE_SEC, buffer_max: int = BUFFER_MAX, recv_tick: float = RECV_TICK, ai_status=None, ai_check=None, ai_refresh=None,
                 ws_max: int = WS_MESSAGE_MAX, silence_max: float = SILENCE_MAX, claude_factory=None,
                 codex_factory=None):
        """token = 글자 또는 공급 함수(호출할 때마다 키 저장소를 다시 읽는다)."""
        self.url = url
        self.registry = registry or ProviderRegistry.from_providers([provider] if provider is not None else [])
        from .chat_claude import ClaudeProviderFactory
        from .chat_codex import CodexProviderFactory
        if claude_factory is not None and type(claude_factory) is not ClaudeProviderFactory:
            raise ValueError("claude-factory")
        if codex_factory is not None and type(codex_factory) is not CodexProviderFactory:
            raise ValueError("codex-factory")
        self.claude_factory = claude_factory
        self.codex_factory = codex_factory
        self.ref_store = ref_store
        # Legacy attributes remain for the single-flight stop path; turns resolve from the registry.
        self.provider = provider
        self.token_fn = token if callable(token) else (lambda: token)
        self.ws_max, self.silence_max = ws_max, silence_max
        self.agent_version = agent_version
        self.connect = connect
        # ai_status = hello.ai_links {공급자: 상태 낱말}. 그 밖의 값은 hello 에 싣지 않는다.
        # ai_check(provider) -> 상태 낱말: 턴마다 이 PC 의 끊기 표시와 CLI 로그인을 다시 본다(None 이면 보지 않는다 — --fake).
        # ai_refresh() -> (ai_links, claude_factory, codex_factory): 앱이 연결을 바꿨을 때(desktop control ai-refresh).
        self.ai_status = self._clean_links(ai_status)
        self.ai_check, self.ai_refresh = ai_check, ai_refresh
        self.backoff = backoff or wsclient.Backoff()
        self.stopping = stopping or threading.Event()
        self.log = log or (lambda rec: None)
        self.coalesce, self.buffer_max, self.recv_tick = coalesce, buffer_max, recv_tick
        self.ws = None
        self.ws_lock = threading.Lock()
        # 내보내기 순서 잠금 — 턴 스레드의 「버퍼에 넣고 보내기」와 재연결의 「hello → 미확인 재전송」을 직렬화한다.
        # 없으면 재연결 순간 새 seq 가 재전송보다 먼저 나가 서버가 빈 칸으로 버리고, 다음 재연결까지 그 seq 가 묶인다.
        self.out_lock = threading.RLock()
        self.buffers: OrderedDict = OrderedDict()   # turn_id → TurnBuffer
        self.current: str | None = None             # 실행 중 turn_id(공급자 하나 = 턴 하나)
        self.current_provider = None
        self.seen: OrderedDict = OrderedDict()      # 받은 turn_id(최근 SEEN_MAX) — 버퍼를 비운 뒤에도 같은 턴을 다시 실행하지 않는다
        self.threads: list = []
        self.connects = 0
        self.session_bindings = {}  # session_id -> (provider, model)

    @staticmethod
    def _clean_links(value):
        from .ai_connection import PROVIDERS, STATES
        return {k: v for k, v in value.items() if k in PROVIDERS and v in STATES} if isinstance(value, dict) else None

    def _hello(self) -> str:
        caps = self.registry.capabilities()
        if self.claude_factory is not None:
            caps.append({"provider": "claude", "models": list(self.claude_factory.models)})
        if self.codex_factory is not None:
            caps.append({"provider": "codex", "models": list(self.codex_factory.models)})
        hello = {"type": "hello", "agent_version": self.agent_version,
                 "providers": [c["provider"] for c in caps], "capabilities_version": 2, "capabilities": caps}
        if self.ai_status is not None:
            hello[HELLO_AI_KEY] = dict(self.ai_status)
        return _dumps(hello)

    def _resend_hello(self) -> None:
        """같은 연결에서 hello 를 다시 보낸다(AI 연결이 바뀌었을 때). 연결이 없으면 다음 연결의 hello 가 싣는다."""
        with self.out_lock:
            self._send(self._hello())

    def refresh_ai(self) -> None:
        """앱이 AI 연결을 바꿨다(ai:connect, ai:disconnect): 다시 확인하고 factory 를 바꾼 뒤 hello 를 다시 보낸다."""
        if not callable(self.ai_refresh):
            return
        try:
            links, claude_factory, codex_factory = self.ai_refresh()
        except Exception:
            self.log({"event": "ai-refresh", "error": "failed"})
            return
        from .chat_claude import ClaudeProviderFactory
        from .chat_codex import CodexProviderFactory
        self.claude_factory = claude_factory if type(claude_factory) is ClaudeProviderFactory else None
        self.codex_factory = codex_factory if type(codex_factory) is CodexProviderFactory else None
        self.ai_status = self._clean_links(links)
        self.log({"event": "ai-refresh", "ok": True})
        self._resend_hello()

    def _ai_state(self, provider_name):
        try:
            state = self.ai_check(provider_name)
        except Exception:
            state = "missing"
        from .ai_connection import STATES
        return state if state in STATES else "missing"

    # ── 보내기 ──
    def _send(self, msg: str) -> bool:
        with self.ws_lock:
            ws = self.ws
        if ws is None:
            return False
        try:
            ws.send_text(msg)
            return True
        except wsclient.WsError:
            return False

    def _stop_provider(self, provider) -> bool:
        try:
            provider.stop()
            return True
        except Exception:
            self.log({"event": "turn", "error": "PROVIDER-STOP"})
            return False

    def _resend(self) -> None:
        for b in list(self.buffers.values()):
            for m in b.pending():
                if not self._send(m):
                    return

    def _gc(self) -> None:
        for tid in [t for t, b in self.buffers.items() if b.done() and t != self.current]:
            del self.buffers[tid]

    # ── 턴 실행 ──
    def _run_turn_managed(self, session_id: str, turn_id: str, text: str, provider, ref, approval_outcomes) -> None:
        try:
            self._run_turn(session_id, turn_id, text, provider, ref, approval_outcomes)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def _run_turn(self, session_id: str, turn_id: str, text: str, provider, ref, approval_outcomes=()) -> None:
        buf = self.buffers[turn_id]
        q: queue.Queue = queue.Queue()

        def pump():
            try:
                if approval_outcomes:
                    turn_events = provider.start_turn(text, ref, approval_outcomes=approval_outcomes)
                else:
                    turn_events = provider.start_turn(text, ref)
                for kind, data in turn_events:
                    q.put((kind, data))
            except Exception as e:   # 공급자 실패 — 코드만
                q.put(("error", {"code": "PROVIDER-" + type(e).__name__[:20].upper()}))
            q.put(None)

        th = threading.Thread(target=pump, name="chat-provider", daemon=True)
        th.start()
        pend, first = [], None   # 묶는 중인 delta 글 · 첫 delta 시각
        over = False

        def emit(kind, data, force=False):
            for part in fit_event(turn_id, kind, data, self.ws_max):   # 메시지 하나 ≤ ws_max(서버 1009 방지)
                one(kind, part, force)

        def one(kind, data, force=False):
            nonlocal over
            if over and not force:
                return
            if kind in TERMINAL:   # 끝 이벤트를 보내기 전에 비운다 — 서버가 받자마자 다음 turn.start 를 보낼 수 있다
                self.current = None
            with self.out_lock:
                msg = buf.add(kind, data, force=force)
                if msg is None:   # 버퍼 상한 — 공급자를 멈추고 끝 이벤트로 닫는다
                    over = True
                    self._stop_provider(provider)
                    self.current = None
                    msg = buf.add("error", {"code": "BUFFER-LIMIT"}, force=True)
                    self.log({"event": "turn", "error": "BUFFER-LIMIT"})
                self._send(msg)

        def flush():
            nonlocal pend, first
            if pend:
                emit("delta", {"text": "".join(pend)})
            pend, first = [], None

        ended = False
        while True:
            wait = None if first is None else max(0.0, self.coalesce - (time.monotonic() - first))
            try:
                item = q.get(timeout=wait)
            except queue.Empty:
                flush()
                continue
            if item is None:
                break
            kind, data = item
            if kind == "session_ref":
                cli_ref = data.get("cli_session_ref")
                if isinstance(cli_ref, str) and cli_ref and len(cli_ref) <= 512:
                    handle = secrets.token_urlsafe(32)
                    model = self.session_bindings[session_id][1]
                    if self.ref_store and self.ref_store.put(handle, session_id, provider.name, model, cli_ref):
                        self._send(_dumps({"type": "session_ref", "session_id": session_id, "cli_session_ref": handle}))
                continue
            if kind not in KINDS or not isinstance(data, dict) or ended:
                continue
            if kind == "delta":
                t = data.get("text")
                if isinstance(t, str) and t:
                    pend.append(t)
                    first = first if first is not None else time.monotonic()
                continue
            flush()
            if over:
                ended = kind in TERMINAL or ended
                continue
            emit(kind, data, force=kind in TERMINAL)
            ended = kind in TERMINAL
        flush()
        if not ended and not over:
            emit("done", {}, force=True)
        th.join(1.0)
        if self.current == turn_id:
            self.current = None
        self.log({"event": "turn", "end": "ok" if not over else "buffer"})

    def _on(self, m: dict) -> None:
        typ = m.get("type")
        if typ == "ping":
            self._send(_dumps({"type": "pong"}))
        elif typ == "ack":
            b = self.buffers.get(m.get("turn_id"))
            if b and isinstance(m.get("seq"), int):
                b.ack(m["seq"])
                self._gc()
        elif typ == "turn.stop":
            if m.get("turn_id") == self.current:
                if self.current_provider is not None:
                    self._stop_provider(self.current_provider)
        elif typ == "turn.start":
            tid, sid, text = m.get("turn_id"), m.get("session_id"), m.get("text")
            if not (isinstance(tid, str) and isinstance(sid, str) and isinstance(text, str)) or tid in self.seen:
                return   # 모양이 틀렸거나 이미 받은 턴 — 다시 실행하지 않는다(D6)
            try:
                if "approval_outcomes" in m and m["approval_outcomes"] is None:
                    raise ValueError("approval-outcomes-shape")
                approval_outcomes = normalize_approval_outcomes(m.get("approval_outcomes"))
            except ValueError:
                b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                self.seen[tid] = True
                self._send(b.add("error", {"code": "APPROVAL-OUTCOMES"}, force=True))
                return
            provider_name, model = m.get("provider"), m.get("model")
            factory = None
            if provider_name == "claude":
                if (self.claude_factory is None or m.get("binding_version") != 2
                        or model not in self.claude_factory.models):
                    provider = None
                else:
                    factory = self.claude_factory
                    provider = None
            elif provider_name == "codex":
                if (self.codex_factory is None or m.get("binding_version") != 2
                        or model not in self.codex_factory.models):
                    provider = None
                else:
                    factory = self.codex_factory
                    provider = None
            else:
                try:
                    provider = self.registry.validate_turn(provider_name, model, m.get("binding_version"))
                except ProviderUnavailable:
                    provider = None
            if factory is not None and callable(self.ai_check):
                # 대화 시작 때 AI 연결을 다시 본다(명세 1.3): 끊기 표시나 로그아웃은 앱이 알리기 전에도 지켜진다.
                state = self._ai_state(provider_name)
                if self.ai_status is not None and self.ai_status.get(provider_name) != state:
                    self.ai_status[provider_name] = state
                    self._resend_hello()
                if state != "linked":
                    b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                    self.seen[tid] = True
                    self._send(b.add("error", {"code": AI_REFUSALS[state]}, force=True))
                    return
            if provider is None and factory is None:
                b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                self.seen[tid] = True
                self._send(b.add("error", {"code": "PROVIDER-BINDING"}, force=True))
                return
            binding = (provider_name, model)
            previous = self.session_bindings.get(sid)
            if previous is not None and previous != binding:
                b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                self.seen[tid] = True
                self._send(b.add("error", {"code": "PROVIDER-BINDING"}, force=True))
                return
            if self.current is not None:   # 서버가 세션당 1턴을 지킨다 — 그래도 겹치면 실행하지 않고 끝 이벤트만
                b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                self._send(b.add("error", {"code": "PC-BUSY"}, force=True))
                return
            if factory is not None:
                try:
                    provider = factory.create_turn(sid, tid, m.get("launch_authorization_path"),
                                                   provider_name, model)
                except Exception:
                    b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                    self.seen[tid] = True
                    self._send(b.add("error", {"code": "PROVIDER-BINDING"}, force=True))
                    return
            if self.ref_store and not self.ref_store.bind_session(sid, *binding):
                close = getattr(provider, "close", None)
                if callable(close): close()
                b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                self.seen[tid] = True
                self._send(b.add("error", {"code": "PROVIDER-BINDING"}, force=True))
                return
            handle = m.get("cli_session_ref")
            ref = None
            if handle is not None:
                ref = self.ref_store.get(handle, sid, provider_name, model) if self.ref_store else None
                if not ref:
                    close = getattr(provider, "close", None)
                    if callable(close): close()
                    b = self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
                    self.seen[tid] = True
                    self._send(b.add("error", {"code": "CLI-SESSION-REF"}, force=True))
                    return
            self.session_bindings[sid] = binding
            self.seen[tid] = True
            while len(self.seen) > SEEN_MAX:
                self.seen.popitem(last=False)
            self.buffers[tid] = TurnBuffer(tid, self.buffer_max)
            self.current = tid
            self.current_provider = provider
            th = threading.Thread(target=self._run_turn_managed,
                                  args=(sid, tid, text, provider, ref, approval_outcomes),
                                  name="chat-turn", daemon=True)
            self.threads.append(th)
            th.start()

    # ── 연결 ──
    def _session(self, ws) -> str:
        """연결 하나 — hello → 미확인 재전송 → 받기. 끝난 이유."""
        if hasattr(ws, "stall_max"):   # 메시지 중간 대기도 같은 상한(반쯤 보낸 채 멈춘 연결)
            ws.stall_max = self.silence_max
        with self.out_lock:   # hello·재전송이 끝날 때까지 턴 스레드의 새 이벤트를 붙든다(seq 순서 보장)
            with self.ws_lock:
                self.ws = ws
            self._send(self._hello())
            self._resend()
        try:
            while not self.stopping.is_set():
                try:
                    raw = ws.recv(timeout=self.recv_tick)
                except socket.timeout:
                    if time.monotonic() - getattr(ws, "last_rx", time.monotonic()) > self.silence_max:
                        return "silent"   # 서버 ping 이 끊겼다 — 반쯤 열린 연결로 보고 다시 붙는다
                    continue
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(m, dict):
                    self._on(m)
            return "signal"
        except wsclient.WsError as e:
            if e.kind == "closed" and e.code == 4001:
                return "auth-closed"
            return "closed" if e.kind == "closed" else "network"
        finally:
            with self.ws_lock:
                self.ws = None
            ws.close()

    def _fresh_token(self, used: str) -> bool:
        """인증 거절 뒤 — 키 저장소를 다시 읽어 토큰이 바뀌었으면 True(새 토큰으로 다시), 같거나 없으면 False(멈춤)."""
        try:
            new = self.token_fn()
        except Exception:
            new = None
        return bool(new) and new != used

    def run(self) -> str:
        while not self.stopping.is_set():
            token = self.token_fn() or ""
            try:
                ws = self.connect(self.url, {"Authorization": "Bearer " + token})
            except wsclient.WsError as e:
                if e.status in (401, 403):
                    if self._fresh_token(token):
                        self.log({"event": "connect", "error": "auth", "status": e.status, "why": "token-changed"})
                        continue
                    self.log({"event": "connect", "error": "auth", "status": e.status})
                    return "auth"
                self.log({"event": "connect", "error": e.kind, "status": e.status})
                self.stopping.wait(self.backoff.next())
                continue
            self.connects += 1
            self.backoff.reset()
            self.log({"event": "connect", "ok": True})
            why = self._session(ws)
            self.log({"event": "disconnect", "why": why})
            if why == "auth-closed" and not self._fresh_token(token):
                return "auth"
            if why not in ("signal", "auth-closed"):
                self.stopping.wait(self.backoff.next())
        if self.current:
            if self.current_provider is not None:
                self._stop_provider(self.current_provider)
        return "signal"
