"""HTTP authorization and body contract for chat confirmation."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import webchat


class Request:
    path_params = {"sid": "cs_" + "a" * 24, "aid": "ca_" + "b" * 24}
    def __init__(self, method="GET", body=b"{}"):
        self.method, self._body = method, body
    async def body(self):
        return self._body


class ApprovalHttpTests(unittest.TestCase):
    def setUp(self):
        async def uid(_request):
            return "synthetic-user"
        self.site = SimpleNamespace(uid_of=uid, same_origin=lambda _request: True)
        self.routes = webchat.Routes(self.site, None)

    def test_confirm_requires_same_origin(self):
        self.site.same_origin = lambda _request: False
        with patch("webchat.enabled", return_value=True), patch("webchat.approval_confirm") as confirm:
            response = asyncio.run(self.routes.approval_confirm(Request("POST")))
        self.assertEqual(response.status_code, 403)
        confirm.assert_not_called()

    def test_confirm_rejects_op_or_params_from_browser(self):
        with patch("webchat.enabled", return_value=True), patch("webchat.approval_confirm") as confirm:
            response = asyncio.run(self.routes.approval_confirm(Request("POST", b'{"op":"record_edit"}')))
        self.assertEqual(response.status_code, 400)
        confirm.assert_not_called()

    def test_list_returns_server_approvals_only(self):
        with patch("webchat.enabled", return_value=True), patch("webchat.approvals_list", return_value=[{"id": "ca_x"}]):
            response = asyncio.run(self.routes.approvals(Request()))
        self.assertEqual(json.loads(response.body), {"approvals": [{"id": "ca_x"}]})
        self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
