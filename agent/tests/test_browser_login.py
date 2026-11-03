"""브라우저 로그인(앱 없는 대체 경로) — PKCE·state·127.0.0.1 1회 수신기. 실제 브라우저·서버를 쓰지 않는다."""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import os
import re
import unittest

from agent import config as _config, migrate, uploader
from agent.tests.helpers import STREAM_ID, FakeImportServer, MemoryKeyStore, TempHome, fake_browser, run_cli


def _get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.request("GET", path)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")
    finally:
        c.close()


class PkceTest(unittest.TestCase):
    def test_pair_shape(self):
        v, ch = uploader.pkce_pair()
        self.assertRegex(v, r"^[A-Za-z0-9_-]{43}$")
        self.assertRegex(ch, r"^[A-Za-z0-9_-]{43}$")
        want = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(ch, want)
        self.assertNotEqual(uploader.pkce_pair()[0], v)
        self.assertTrue(16 <= len(uploader.new_state()) <= 64)
        self.assertRegex(uploader.new_state(), r"^[A-Za-z0-9_-]+$")


class LoopbackTest(unittest.TestCase):
    CODE = "C" * 43

    def test_receives_code_once(self):
        st = uploader.new_state()
        rx = uploader.LoopbackReceiver(st)
        self.assertTrue(re.match(r"^http://127\.0\.0\.1:\d+/cb$", rx.redirect_uri))
        self.assertEqual(rx._httpd.server_address[0], "127.0.0.1")
        status, body = _get(rx.port, f"/cb?code={self.CODE}&state={st}")
        self.assertEqual(status, 200)
        self.assertNotIn(self.CODE, body)
        self.assertEqual(rx.wait(1), self.CODE)

    def test_rejects_wrong_state_path_or_code_and_keeps_waiting(self):
        st = uploader.new_state()
        rx = uploader.LoopbackReceiver(st)
        try:
            for path in (f"/cb?code={self.CODE}&state=other-state-value-x",      # 다른 state
                         f"/cb?code={self.CODE}",                                # state 없음
                         f"/other?code={self.CODE}&state={st}",                  # 다른 경로
                         f"/cb?code=short&state={st}",                           # code 형식
                         f"/cb?code={self.CODE}&code={self.CODE}&state={st}"):  # code 두 번
                with self.subTest(path):
                    self.assertEqual(_get(rx.port, path)[0], 400)
            self.assertFalse(rx._event.is_set())
            self.assertEqual(_get(rx.port, f"/cb?code={self.CODE}&state={st}")[0], 200)
            self.assertEqual(_get(rx.port, f"/cb?code={'D' * 43}&state={st}")[0], 400)   # 두 번째는 안 받는다
            self.assertEqual(rx._code, self.CODE)
        finally:
            rx.close()

    def test_error_redirect_stops_now_only_with_matching_state(self):
        st = uploader.new_state()
        rx = uploader.LoopbackReceiver(st)
        self.assertEqual(_get(rx.port, "/cb?error=access_denied&state=wrong-state-value-xx")[0], 400)   # 남의 state 는 무시
        self.assertFalse(rx._event.is_set())
        self.assertEqual(_get(rx.port, f"/cb?error=access_denied&state={st}")[0], 200)
        with self.assertRaises(uploader.LoginError) as cm:
            rx.wait(1)
        self.assertEqual((cm.exception.kind, cm.exception.code), ("denied", "access_denied"))

    def test_error_messages(self):
        for code in ("access_denied", "login_failed", "login_expired", "account_unavailable", "server_error", "other_x"):
            with self.subTest(code):
                line = uploader.explain_login_error(uploader.LoginError("denied", code=code))[0]
                self.assertIn(f"({code}). 다시 실행하세요.", line)

    def test_timeout(self):
        rx = uploader.LoopbackReceiver(uploader.new_state())
        with self.assertRaises(uploader.LoginError) as cm:
            rx.wait(0.2)
        self.assertEqual(cm.exception.kind, "timeout")


class BrowserLoginCliTest(unittest.TestCase):
    """connect --browser · migrate login --browser — 가짜 서버(/desktop/login → 302 → 127.0.0.1 /cb, /desktop/cli/claim)."""

    def setUp(self):
        self.th = TempHome()
        self.srv = FakeImportServer()
        self.ks = MemoryKeyStore()
        self.opened = []
        self.outs = []
        self.kw = dict(ks_factory=lambda service: self.ks, browser_open=fake_browser(self.opened), login_timeout=10,
                       getpass_fn=lambda prompt: self.fail("getpass used"), stdin=io.StringIO(""))

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def cli(self, *argv):
        code, out = run_cli(["--home", self.th.home] + list(argv), **self.kw)
        self.outs.append(out)
        return code, out

    def assert_secrets_absent(self, *values):
        for out in self.outs:
            for v in values:
                self.assertNotIn(v, out)
        for root, _dirs, files in os.walk(self.th.root):
            for fn in files:
                with open(os.path.join(root, fn), "rb") as f:
                    data = f.read()
                for v in values:
                    self.assertNotIn(v.encode(), data, fn)

    def test_connect_browser(self):
        code, out = self.cli("connect", "--server", self.srv.url, "--browser", "--label", "synthetic-pc")
        self.assertEqual(code, 0, out)
        token = self.ks.get(_config.token_account(STREAM_ID))
        self.assertEqual(token, self.srv.token)
        self.assertTrue(token.startswith("imp_" + STREAM_ID + "."))
        self.assertIn("계정: synth@example.invalid", out)
        self.assertEqual(_config.load(self.th.paths)["source_instance_id"], STREAM_ID)
        # 로그인 시작 주소: challenge·state·redirect_uri(127.0.0.1:<port>/cb) — verifier 는 주소에 없다
        q = self.srv.login_requests[0]
        self.assertRegex(q["redirect_uri"], r"^http://127\.0\.0\.1:\d+/cb$")
        self.assertEqual(len(self.opened), 1)
        self.assertIn(self.opened[0], out)            # 브라우저가 안 열릴 때를 위해 주소를 보여 준다
        hdrs, form = self.srv.claim_requests[0]
        self.assertEqual((form["scope"], form["client_name"]), ("device", "synthetic-pc"))
        self.assertEqual(form["state"], q["state"])
        self.assertNotIn(form["verifier"], self.opened[0])
        self.assertNotIn("Origin", hdrs)
        self.assertNotIn("X-MyCRM-Desktop", hdrs)
        self.assert_secrets_absent(token, form["verifier"], form["code"])

    def test_connect_browser_default_client_name(self):
        code, out = self.cli("connect", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.srv.claim_requests[0][1]["client_name"], uploader.default_client_name())

    def test_connect_browser_claim_rejected_saves_nothing(self):
        for forced, expect in (((400, {"code": "HANDOFF-INVALID", "msg": "다시 로그인해 주세요"}), "로그인부터"),
                               ((403, {"code": "NAME-REQUIRED", "msg": "표시 이름이 필요해요",
                                       "action": "웹에서 표시 이름을 정하세요"}), "웹에서 표시 이름을 정하세요"),
                               ((429, {"code": "RATE-LIMIT"}), "RATE-LIMIT")):
            with self.subTest(expect):
                self.srv.claim_script = [forced]
                code, out = self.cli("connect", "--server", self.srv.url, "--browser")
                self.assertEqual(code, 1, out)
                self.assertIn(expect, out)
                self.assertEqual(self.ks.items, {})
                self.assertFalse(os.path.exists(self.th.paths.config))

    def test_connect_browser_timeout(self):
        self.kw.update(browser_open=lambda url: False, login_timeout=0.3)    # 브라우저가 안 열리고 아무도 안 옴
        code, out = self.cli("connect", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 1, out)
        self.assertIn("브라우저 로그인을 받지 못했어요", out)
        self.assertEqual(self.srv.claim_requests, [])
        self.assertEqual(self.ks.items, {})

    def test_connect_browser_stores_first_and_run_once_finishes(self):
        # claim 뒤 서버 확인이 실패(503) — 서버엔 장치가 생겼으니 토큰을 Keychain 에 남기고 다음 run-once 가 마친다
        self.srv.device_script = [(503, {"code": "IMPORTS-OFF"})]
        code, out = self.cli("connect", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 1, out)
        self.assertIn("다음 `run-once` 때 확인을 마칩니다", out)
        token = self.srv.token
        self.assertEqual(self.ks.get(_config.token_account(STREAM_ID)), token)
        self.assertIsNone(_config.load(self.th.paths).get("source_instance_id"))
        code, out = self.cli("status")
        self.assertIn("서버 확인 대기", out)
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertIn("연결했어요(서버 확인 완료)", out)
        self.assertEqual(_config.load(self.th.paths)["source_instance_id"], STREAM_ID)
        self.assertFalse(os.path.exists(os.path.join(self.th.home, "connect-pending.json")))
        code, out = self.cli("status")
        self.assertNotIn("서버 확인 대기", out)
        self.assert_secrets_absent(token)

    def test_connect_browser_check_rejected_deletes_token(self):
        self.srv.device_script = [(401, {"code": "AUTH-INVALID"})]
        code, out = self.cli("connect", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 1, out)
        self.assertIn("지웠어요", out)
        self.assertEqual(self.ks.items, {})
        self.assertFalse(os.path.exists(os.path.join(self.th.home, "connect-pending.json")))

    def test_connect_browser_error_redirect_stops_without_claim(self):
        import urllib.parse
        import urllib.request

        def deny(url):     # 서버가 로그인 취소를 loopback 으로 알려 오는 경우
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            back = q["redirect_uri"] + "?" + urllib.parse.urlencode({"error": "access_denied", "state": q["state"]})
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(back, timeout=5).read()
            except Exception:
                pass
        self.kw.update(browser_open=deny, login_timeout=30)
        code, out = self.cli("connect", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 1, out)
        self.assertIn("로그인을 거절·취소했어요(access_denied)", out)
        self.assertEqual(self.srv.claim_requests, [])
        self.assertEqual(self.ks.items, {})

    def test_loopback_bind_failure(self):
        from unittest import mock
        with mock.patch.object(uploader, "LoopbackReceiver", side_effect=OSError("bind")):
            code, out = self.cli("connect", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 1, out)
        self.assertIn("포트를 열지 못했어요", out)
        self.assertEqual(self.srv.login_requests, [])

    def test_browser_and_token_stdin_exclusive(self):
        with self.assertRaises(SystemExit) as cm:
            self.cli("connect", "--server", self.srv.url, "--browser", "--token-stdin")
        self.assertEqual(cm.exception.code, 2)

    def test_migrate_login_browser(self):
        code, out = self.cli("migrate", "login", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 0, out)
        tok = self.srv.migration_token
        self.assertEqual(self.ks.get(migrate.token_account(self.srv.url)), tok)
        hdrs, form = self.srv.claim_requests[0]
        self.assertEqual(form["scope"], "migration")
        self.assertNotIn("client_name", form)
        self.assertIn("계정: synth@example.invalid", out)
        self.assertIn("처음 쓰일 때 폐기", out)
        self.assert_secrets_absent(tok, form["verifier"], form["code"])

    def test_migrate_login_browser_refused(self):
        self.srv.claim_script = [(403, {"code": "MIGRATION-NOT-ALLOWED", "msg": "허용 목록에 없어요"})]
        code, out = self.cli("migrate", "login", "--server", self.srv.url, "--browser")
        self.assertEqual(code, 1, out)
        self.assertIn("MIGRATION-NOT-ALLOWED", out)
        self.assertEqual(self.ks.items, {})


if __name__ == "__main__":
    unittest.main()
