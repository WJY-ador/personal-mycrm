"""Unregistered Codex app-server dynamic-tool relay candidate."""

import json
import os
import queue
import re
import subprocess
import threading
import time

from .chat_mcp_bridge import MAX_LINE_BYTES

_NAMES = {"mycrm_" + tier: "mcp__my-crm__" + tier
          for tier in ("find", "read", "write", "decide")}


class JsonRpcTransport:
    """Bounded line transport; the caller owns and terminates the subprocess."""
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.messages = queue.Queue(maxsize=128)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        try:
            while True:
                line = self.reader.readline(MAX_LINE_BYTES + 1)
                if not line:
                    self.messages.put((False, None))
                    return
                if len(line) > MAX_LINE_BYTES or not line.endswith(b'\n'):
                    self.messages.put((False, None))
                    return
                try:
                    message = json.loads(line.decode('utf-8'))
                except (UnicodeError, ValueError):
                    self.messages.put((False, None))
                    return
                self.messages.put((True, message))
        except Exception:
            self.messages.put((False, None))

    def send(self, message):
        raw = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8') + b'\n'
        if len(raw) > MAX_LINE_BYTES:
            raise ValueError('message-too-large')
        self.writer.write(raw)
        self.writer.flush()

    def receive(self, timeout):
        try:
            valid, message = self.messages.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError() from None
        if not valid or not isinstance(message, dict):
            raise ValueError('invalid-or-closed-stream')
        return message


class AppServerProcess:
    """Unregistered process runner; caller must validate argv, env, and grant.

    A finished turn does not imply that the process and its children stopped.
    Completion is therefore emitted only after the supervisor confirms cleanup.
    """
    def __init__(self, supervisor, relay, consent_current, *, timeout):
        self.supervisor = supervisor
        self.relay = relay
        self.consent_current = consent_current
        self.timeout = timeout
        self._state_lock = threading.Lock()
        self._termination_lock = threading.Lock()
        self._stopping = threading.Event()
        self._proc = None
        self._terminated = False

    def _terminate(self, proc):
        with self._termination_lock:
            if not self._terminated:
                self.supervisor.terminate_tree(proc)
                self._terminated = True

    def stop(self):
        self._stopping.set()
        with self._state_lock:
            proc = self._proc
        if proc is not None:
            self._terminate(proc)

    def run(self, argv, *, cwd, env, model, text, thread_ref=None, developer_instructions='',
            require_authenticated_account=False):
        if self._stopping.is_set() or self.consent_current() is not True:
            raise ValueError('consent-revoked')
        proc = None
        completed = False
        try:
            proc = self.supervisor.spawn(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            with self._state_lock:
                self._proc = proc
            if self._stopping.is_set():
                raise ValueError('consent-revoked')
            transport = JsonRpcTransport(proc.stdout, proc.stdin)
            turn = AppServerTurn(transport, self.relay,
                                 lambda: not self._stopping.is_set() and self.consent_current() is True,
                                 timeout=self.timeout)
            for kind, data in turn.run(model=model, cwd=cwd, text=text, thread_ref=thread_ref,
                                       developer_instructions=developer_instructions,
                                       require_authenticated_account=require_authenticated_account):
                if kind == 'done':
                    completed = True
                else:
                    yield kind, data
        except Exception:
            if self._stopping.is_set():
                raise ValueError('consent-revoked') from None
            raise
        finally:
            if proc is not None:
                try:
                    self._terminate(proc)
                finally:
                    for stream in (proc.stdin, proc.stdout):
                        if stream:
                            try:
                                stream.close()
                            except BrokenPipeError:
                                if not self._stopping.is_set():
                                    raise
                    with self._state_lock:
                        self._proc = None
        if completed and not self._stopping.is_set():
            yield 'done', {}


class DynamicToolRelay:
    def __init__(self, bridge):
        self.bridge = bridge

    def tools(self):
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        response = self.bridge.handle_line(request)
        if not response:
            raise ValueError("bridge-unavailable")
        result = json.loads(response)
        if not isinstance(result, dict) or not isinstance(result.get("result"), dict):
            raise ValueError("bridge-denied")
        definitions = result["result"].get("tools")
        if not isinstance(definitions, list):
            raise ValueError("bridge-shape")
        reverse = {value: key for key, value in _NAMES.items()}
        out = []
        seen = set()
        for definition in definitions:
            if not isinstance(definition, dict) or definition.get("name") not in reverse:
                raise ValueError("bridge-tool")
            name = reverse[definition["name"]]
            if name in seen or not isinstance(definition.get("inputSchema"), dict):
                raise ValueError("bridge-tool")
            seen.add(name)
            description = definition.get("description", "")
            if name == "mycrm_decide":
                description = ("변경을 바로 실행하지 않고 사용자 확인 카드를 요청합니다. "
                    "먼저 mycrm_read의 decide_preview로 bind를 받은 뒤 op, params, bind를 전달하세요. "
                    "서버가 요청을 지원하고 사용자가 카드에서 확인한 경우에만 변경이 실행됩니다. "
                    "대기 중인 변경을 완료했다고 말하지 마세요.")
            out.append({"type": "function", "name": name,
                        "description": description,
                        "inputSchema": definition["inputSchema"]})
        return out

    def call(self, name, args):
        denied = {"success": False, "contentItems": [{"type": "inputText", "text": "MyCRM tool call denied"}]}
        if not isinstance(name, str) or name not in _NAMES or not isinstance(args, dict):
            return denied
        try:
            request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": _NAMES[name], "arguments": args}},
                                 ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if len(request.encode("utf-8")) > MAX_LINE_BYTES:
                return denied
            response = self.bridge.handle_line(request)
            if not response:
                return denied
            result = json.loads(response).get("result")
            if not isinstance(result, dict) or result.get("isError") is not False:
                return denied
            content = result.get("content")
            if (not isinstance(content, list) or len(content) != 1
                    or not isinstance(content[0], dict) or content[0].get("type") != "text"
                    or not isinstance(content[0].get("text"), str)):
                return denied
            return {"success": True, "contentItems": [{"type": "inputText", "text": content[0]["text"]}]}
        except (TypeError, ValueError, UnicodeError, RecursionError):
            return denied


class DynamicRequestDispatcher:
    def __init__(self, relay, thread_id, turn_id):
        if not all(isinstance(item, str) and 0 < len(item) <= 256 for item in (thread_id, turn_id)):
            raise ValueError("turn-binding")
        self.relay, self.thread_id, self.turn_id = relay, thread_id, turn_id
        self._calls = set()
        self._requests = set()
        self._lock = threading.Lock()

    def dispatch(self, message):
        if not isinstance(message, dict) or message.get("method") != "item/tool/call":
            raise ValueError("unexpected-server-request")
        request_id, params = message.get("id"), message.get("params")
        if (not isinstance(request_id, (str, int)) or isinstance(request_id, bool)
                or isinstance(request_id, str) and not 0 < len(request_id) <= 128):
            raise ValueError("request-id")
        denied = {"id": request_id, "result": {"success": False,
            "contentItems": [{"type": "inputText", "text": "MyCRM tool call denied"}]}}
        if not isinstance(params, dict) or set(params) - {"threadId", "turnId", "callId", "tool", "arguments", "namespace"}:
            return denied
        call_id = params.get("callId")
        if (params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id
                or params.get("namespace") is not None or not isinstance(call_id, str)
                or not 0 < len(call_id) <= 128):
            return denied
        with self._lock:
            if len(self._calls) >= 100 or request_id in self._requests or call_id in self._calls:
                return denied
            self._requests.add(request_id)
            self._calls.add(call_id)
        return {"id": request_id, "result": self.relay.call(params.get("tool"), params.get("arguments"))}


class AppServerTurn:
    def __init__(self, transport, relay, consent_current, *, timeout):
        if not callable(consent_current) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("turn-configuration")
        self.transport, self.relay = transport, relay
        self.consent_current, self.timeout = consent_current, float(timeout)

    def run(self, *, model, cwd, text, thread_ref=None, developer_instructions="",
            require_authenticated_account=False):
        if (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,120}", model)
                or not isinstance(cwd, str) or not os.path.isabs(cwd)
                or not isinstance(text, str) or len(text) > 8000 or "\x00" in text
                or not isinstance(developer_instructions, str) or len(developer_instructions) > 64000):
            raise ValueError("turn-input")
        thread_pattern = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        if thread_ref is not None and (not isinstance(thread_ref, str) or not re.fullmatch(thread_pattern, thread_ref)):
            raise ValueError("thread-ref")
        deadline = time.monotonic() + self.timeout
        buffered = []

        def receive():
            while True:
                if self.consent_current() is not True:
                    raise ValueError("consent-revoked")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("turn-timeout")
                try:
                    message = self.transport.receive(min(remaining, 1.0))
                    break
                except TimeoutError:
                    continue
            if (not isinstance(message, dict)
                    or len(json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_LINE_BYTES):
                raise ValueError("message-shape")
            return message

        def request(request_id, method, params):
            self.transport.send({"id": request_id, "method": method, "params": params})
            while True:
                message = receive()
                if message.get("id") == request_id and "method" not in message:
                    result = message.get("result")
                    if not isinstance(result, dict) or "error" in message:
                        raise ValueError("request-failed")
                    return result
                if "id" in message and "method" in message:
                    raise ValueError("early-server-request")
                if len(buffered) >= 100:
                    raise ValueError("early-events")
                buffered.append(message)

        request(1, "initialize", {"clientInfo": {"name":"mycrm", "version":"1"},
                                   "capabilities":{"experimentalApi":True}})
        self.transport.send({"method":"initialized", "params":{}})
        if require_authenticated_account:
            account_result = request(4, "account/read", {"refreshToken": False})
            account = account_result.get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                raise ValueError("login-required")
        thread_params = {"model":model, "cwd":cwd, "sandbox":"read-only",
                         "developerInstructions":developer_instructions}
        if thread_ref is None:
            thread_params.update({"dynamicTools": self.relay.tools(), "environments": []})
            thread_result = request(2, "thread/start", thread_params)
        else:
            thread_params["threadId"] = thread_ref
            thread_result = request(2, "thread/resume", thread_params)
        thread = thread_result.get("thread")
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not re.fullmatch(thread_pattern, thread_id) or thread_ref is not None and thread_id != thread_ref:
            raise ValueError("thread-binding")
        yield "session_ref", {"cli_session_ref": thread_id}
        turn_result = request(3, "turn/start", {"threadId":thread_id, "model":model,
            "cwd":cwd, "input":[{"type":"text", "text":text, "text_elements":[]}],
            "environments":[], "sandboxPolicy":{"type":"readOnly", "networkAccess":False}})
        turn = turn_result.get("turn")
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not isinstance(turn_id, str) or not re.fullmatch(thread_pattern, turn_id):
            raise ValueError("turn-binding")
        dispatcher = DynamicRequestDispatcher(self.relay, thread_id, turn_id)
        while True:
            if self.consent_current() is not True:
                raise ValueError("consent-revoked")
            message = buffered.pop(0) if buffered else receive()
            method, params = message.get("method"), message.get("params")
            if "id" in message:
                self.transport.send(dispatcher.dispatch(message))
                continue
            if not isinstance(params, dict):
                continue
            if params.get("threadId") not in (None, thread_id) or params.get("turnId") not in (None, turn_id):
                raise ValueError("event-binding")
            if method in ("item/started", "item/completed"):
                item = params.get("item")
                if not isinstance(item, dict):
                    raise ValueError("item-shape")
                item_type = item.get("type")
                if item_type in ("commandExecution", "fileChange", "mcpToolCall", "webSearch", "imageView"):
                    raise ValueError("unexpected-tool")
                if method == "item/completed" and item_type == "agentMessage":
                    message_text = item.get("text")
                    if not isinstance(message_text, str):
                        raise ValueError("message-shape")
                    if message_text:
                        yield "delta", {"text":message_text}
            elif method == "turn/completed":
                completed = params.get("turn")
                if not isinstance(completed, dict) or completed.get("id") != turn_id or completed.get("status") != "completed":
                    raise ValueError("turn-failed")
                yield "done", {}
                return
