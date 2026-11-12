"""Synthetic OS-local consent bridge client tests; never use real credentials."""
import json
import os
import queue
import socket
import tempfile
import threading
import unittest

from agent.consent_bridge import request_approval, request_revoke


class ConsentBridgeTests(unittest.TestCase):
    def _start_server(self, path, reply):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        server.settimeout(2)
        seen = {}
        errors = queue.Queue()

        def handle():
            try:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(2)
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = conn.recv(1024)
                        if not chunk:
                            raise EOFError("client closed before completing the request")
                        data += chunk
                    seen.update(json.loads(data))
                    conn.sendall(reply)
            except Exception as exc:
                errors.put(exc)

        thread = threading.Thread(target=handle, daemon=True)
        thread.start()

        def cleanup():
            thread.join(3)
            server.close()
            self.assertFalse(thread.is_alive(), "consent test server did not stop")
            if not errors.empty():
                raise errors.get_nowait()

        self.addCleanup(cleanup)
        return seen

    def _reply(self, reply):
        with tempfile.TemporaryDirectory(prefix="mycrm-consent-bridge-") as root:
            path = os.path.join(root, "c.sock")
            self._start_server(path, reply)
            return request_approval(path, "A" * 43, "req_test_1", "Bearer synthetic-device-token", timeout=2)

    def test_sends_only_request_id_and_bearer_then_requires_affirmative_reply(self):
        with tempfile.TemporaryDirectory(prefix="mycrm-consent-bridge-") as root:
            path = os.path.join(root, "c.sock")
            seen = self._start_server(path, b'{"ok":true}\n')
            self.assertEqual(request_approval(path, "A" * 43, "req_test_1", "Bearer synthetic-device-token", timeout=2),
                             (True, None))
            self.assertEqual(seen, {"version": 1, "token": "A" * 43, "request_id": "req_test_1",
                                    "device_bearer": "Bearer synthetic-device-token"})

    def test_invalid_values_and_negative_reply_fail_closed(self):
        self.assertEqual(request_approval("relative.sock", "A" * 43, "req_test_1", "Bearer synthetic-device-token"),
                         (False, "failed"))
        self.assertEqual(request_approval("/no/such/socket", "A" * 42, "req_test_1", "Bearer synthetic-device-token"),
                         (False, "failed"))
        self.assertEqual(request_approval("/no/such/socket", "A" * 43, "req_test_1", "Bearer synthetic-device-token",
                                          timeout=1), (False, "failed"))
        self.assertEqual(request_approval("/no/such/socket", "A" * 43, "req_test_1", "Bearer synthetic-device-token",
                                          timeout=True), (False, "failed"))
        # A 0.1.3 desktop answers a bare {"ok":false}.
        self.assertEqual(self._reply(b'{"ok":false}\n'), (False, "failed"))

    def test_refusal_reason_is_passed_through_only_from_the_fixed_list(self):
        for reason in ("declined", "locked", "failed"):
            with self.subTest(reason=reason):
                self.assertEqual(self._reply(json.dumps({"ok": False, "reason": reason}).encode() + b"\n"),
                                 (False, reason))
        for reply in (b'{"ok":false,"reason":"DECLINED"}\n', b'{"ok":false,"reason":"other"}\n',
                      b'{"ok":false,"reason":["declined"]}\n', b'{"ok":false,"reason":{"x":1}}\n',
                      b'{"ok":false,"reason":null}\n'):
            with self.subTest(reply=reply):
                self.assertEqual(self._reply(reply), (False, "failed"))

    def test_malformed_replies_fail_closed(self):
        for reply in (b'{"ok":true,"reason":"declined"}\n', b'{"ok":1}\n', b'{"ok":"true"}\n',
                      b'{"ok":true,"extra":1}\n', b'{"reason":"declined"}\n', b'[true]\n', b'true\n',
                      b'not json\n', b'{"ok":true}', b'{"ok":true}\n{"ok":true}\n', b'\xff\n', b''):
            with self.subTest(reply=reply):
                self.assertEqual(self._reply(reply), (False, "failed"))

    def test_revoke_sends_only_the_device_token_and_needs_exact_ok(self):
        with tempfile.TemporaryDirectory(prefix="mycrm-consent-bridge-") as root:
            path = os.path.join(root, "c.sock")
            seen = self._start_server(path, b'{"ok":true}\n')
            self.assertIs(request_revoke(path, "A" * 43, "Bearer synthetic-device-token", timeout=2), True)
            self.assertEqual(seen, {"version": 1, "token": "A" * 43, "kind": "revoke",
                                    "device_bearer": "Bearer synthetic-device-token"})
        for reply in (b'{"ok":false}\n', b'{"ok":false,"reason":"failed"}\n', b'{"ok":true,"extra":1}\n', b'not json\n', b''):
            with self.subTest(reply=reply):
                with tempfile.TemporaryDirectory(prefix="mycrm-consent-bridge-") as root:
                    path = os.path.join(root, "c.sock")
                    self._start_server(path, reply)
                    self.assertIs(request_revoke(path, "A" * 43, "Bearer synthetic-device-token", timeout=2), False)

    def test_revoke_invalid_values_fail_closed(self):
        self.assertIs(request_revoke("relative.sock", "A" * 43, "Bearer synthetic-device-token"), False)
        self.assertIs(request_revoke("/no/such/socket", "A" * 42, "Bearer synthetic-device-token"), False)
        self.assertIs(request_revoke("/no/such/socket", "A" * 43, "synthetic-device-token"), False)
        self.assertIs(request_revoke("/no/such/socket", "A" * 43, "Bearer synthetic-device-token", timeout=True), False)
        self.assertIs(request_revoke("/no/such/socket", "A" * 43, "Bearer synthetic-device-token", timeout=1), False)


if __name__ == "__main__":
    unittest.main()
