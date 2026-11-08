"""Synthetic OS-local consent bridge client tests; never use real credentials."""
import json
import os
import queue
import socket
import tempfile
import threading
import unittest

from agent.consent_bridge import request_approval


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

    def test_sends_only_request_id_and_bearer_then_requires_affirmative_reply(self):
        with tempfile.TemporaryDirectory(prefix="mycrm-consent-bridge-") as root:
            path = os.path.join(root, "c.sock")
            seen = self._start_server(path, b'{"ok":true}\n')
            self.assertTrue(request_approval(path, "A" * 43, "req_test_1", "Bearer synthetic-device-token", timeout=2))
            self.assertEqual(seen, {"version": 1, "token": "A" * 43, "request_id": "req_test_1",
                                    "device_bearer": "Bearer synthetic-device-token"})

    def test_invalid_values_and_negative_reply_fail_closed(self):
        self.assertFalse(request_approval("relative.sock", "A" * 43, "req_test_1", "Bearer synthetic-device-token"))
        self.assertFalse(request_approval("/no/such/socket", "A" * 42, "req_test_1", "Bearer synthetic-device-token"))
        with tempfile.TemporaryDirectory(prefix="mycrm-consent-bridge-") as root:
            path = os.path.join(root, "c.sock")
            self._start_server(path, b'{"ok":false}\n')
            self.assertFalse(request_approval(path, "A" * 43, "req_test_1", "Bearer synthetic-device-token", timeout=2))


if __name__ == "__main__":
    unittest.main()
