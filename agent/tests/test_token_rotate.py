"""장치 토큰 교체(PC 연결 계획 §3) — run-once 자동 교체 · M2(옛 토큰은 새 토큰 첫 사용 때 무효) · M3 계정 전환.
가짜 서버의 rotate 는 새 토큰을 대기로 두고, 새 토큰으로 첫 요청이 오면 그때 옛 토큰을 무효로 한다.
모든 출력·홈 아래 파일에 옛·새 토큰 문자열이 없어야 한다."""
from __future__ import annotations

import datetime as _dt
import io
import os
import unittest

from agent import cli, config as _config, osutil
from agent.tests.helpers import (NAMESPACE, STREAM_ID, TOKEN, FakeImportServer, MemoryKeyStore, TempHome, run_cli,
                                 synth_row, write_jsonl)
from agent.uploader import DeviceError, Uploader

PENDING = cli.pending_token_account(STREAM_ID)
MAIN = _config.token_account(STREAM_ID)


class TokenRotateTest(unittest.TestCase):
    def setUp(self):
        self.th = TempHome()
        self.srv = FakeImportServer()
        self.ks = MemoryKeyStore()
        self.outs = []
        self.kw = dict(ks_factory=lambda service: self.ks, getpass_fn=lambda prompt: TOKEN)

    def tearDown(self):
        self.srv.close()
        self.th.cleanup()

    def cli(self, *argv):
        code, out = run_cli(["--home", self.th.home] + list(argv), **self.kw)
        self.outs.append(out)
        return code, out

    def connect(self):
        code, out = self.cli("connect", "--server", self.srv.url)
        self.assertEqual(code, 0, out)

    def expire_in(self, days):
        cfg = _config.load(self.th.paths)
        cfg["token_expires_at"] = (osutil.kst_now() + _dt.timedelta(days=days)).isoformat(timespec="seconds")
        _config.save(self.th.paths, cfg)

    def rotate_calls(self):
        return [c for c in self.srv.device_calls if c[1] == "/api/device/rotate"]

    def assert_no_secret_leak(self, *tokens):
        tokens = [t for t in tokens if t]
        for out in self.outs:
            for t in tokens:
                self.assertNotIn(t, out)
                self.assertNotIn(t.split(".")[-1], out)     # 비밀 부분만 새도 안 된다
        for root, _dirs, files in os.walk(self.th.root):
            for fn in files:
                with open(os.path.join(root, fn), "rb") as f:
                    data = f.read()
                for t in tokens:
                    self.assertNotIn(t.encode(), data, fn)

    # ---- 자동 교체 ---------------------------------------------------------------
    def test_not_due_no_rotate(self):
        self.connect()            # 가짜 서버 만료 2027-01-18 — 30일 밖
        self.expire_in(31)
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.rotate_calls(), [])
        self.assertNotIn("토큰 교체", out)

    def test_due_rotates_and_promotes(self):
        self.connect()
        self.expire_in(10)
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.rotate_calls()), 1)
        new = self.srv.token
        self.assertNotEqual(new, TOKEN)
        self.assertIsNone(self.srv.pending, "새 토큰이 확인(첫 사용)됐어야 한다")
        self.assertEqual(self.ks.get(MAIN), new)
        self.assertIsNone(self.ks.get(PENDING))
        self.assertIn("새 토큰으로 바꿨어요", out)
        self.assertEqual(_config.load(self.th.paths)["token_expires_at"], self.srv.rotated_expires_at)
        # 옛 토큰은 이제 서버에서 무효
        with self.assertRaises(DeviceError) as cm:
            Uploader(self.srv.url, TOKEN).device()
        self.assertEqual(cm.exception.kind, "auth")
        # 다음 실행은 새 토큰으로 업로드 — 만료가 멀어져 다시 교체하지 않는다
        path = os.path.join(self.th.root, "likes.jsonl")
        write_jsonl(path, [synth_row(1)])
        cfg = _config.load(self.th.paths)
        cfg["adapters"]["likes"].update({"enabled": True, "input_path": path, "provider_code": "synthnet",
                                         "include_kinds": ["kindA"]})
        cfg["upload"]["min_interval_sec"] = 0
        _config.save(self.th.paths, cfg)
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.srv.requests[-1][0].get("Authorization"), "Bearer " + new)
        self.assertEqual(len(self.rotate_calls()), 1)
        self.assert_no_secret_leak(TOKEN, new)

    def test_response_lost_keeps_old_then_next_rotate_overwrites(self):
        self.connect()
        self.expire_in(10)
        self.srv.rotate_script = ["drop"]          # 서버는 새 토큰을 만들었지만 응답이 사라짐
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertIn("다음 실행으로 미뤘어요", out)
        lost = self.srv.pending
        self.assertIsNotNone(lost)
        self.assertEqual(self.ks.get(MAIN), TOKEN)
        self.assertIsNone(self.ks.get(PENDING))
        Uploader(self.srv.url, TOKEN).device()      # M2: 새 토큰이 안 쓰였으니 옛 토큰 그대로 유효
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertIn("새 토큰으로 바꿨어요", out)
        self.assertNotEqual(self.srv.token, lost, "다음 교체가 대기 토큰을 덮어쓴다")
        self.assertEqual(self.ks.get(MAIN), self.srv.token)
        self.assert_no_secret_leak(TOKEN, lost, self.srv.token)

    def test_confirm_fails_keeps_pending_and_old_then_promotes_next_run(self):
        self.connect()
        self.expire_in(10)
        self.srv.device_script = [(503, {"code": "IMPORTS-OFF"})]   # rotate 직후 새 토큰 확인이 실패
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertIn("다음 실행으로 미뤘어요", out)
        new = self.ks.get(PENDING)
        self.assertIsNotNone(new)
        self.assertEqual(self.ks.get(MAIN), TOKEN)
        self.assertEqual(self.srv.pending, new)
        code, out = self.cli("status")
        self.assertIn("교체 대기 토큰: 있음", out)
        # 다음 실행 시작 때 승격 — 교체를 다시 부르지 않는다
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.rotate_calls()), 1)
        self.assertEqual(self.ks.get(MAIN), new)
        self.assertIsNone(self.ks.get(PENDING))
        self.assertEqual(self.srv.token, new)
        self.assert_no_secret_leak(TOKEN, new)

    def test_unknown_pending_discarded_old_kept(self):
        self.connect()
        bogus = "imp_" + STREAM_ID + ".tok_Bogus1." + "B" * 43
        self.ks.set(PENDING, bogus)
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertIn("버렸어요", out)
        self.assertIsNone(self.ks.get(PENDING))
        self.assertEqual(self.ks.get(MAIN), TOKEN)
        self.assert_no_secret_leak(TOKEN, bogus)

    def test_rotate_refused_keeps_token_exit_zero(self):
        for forced, expect in (((409, {"code": "DEVICE-REVOKED"}), "해제됐어요"),
                               ((403, {"code": "ROTATE-DENIED"}), "ROTATE-DENIED"),
                               ((401, {"code": "TOKEN-EXPIRED"}), "TOKEN-EXPIRED")):
            with self.subTest(expect):
                self.connect()
                self.expire_in(5)
                self.srv.rotate_script = [forced]
                code, out = self.cli("run-once")
                self.assertEqual(code, 0, out)
                self.assertIn(expect, out)
                self.assertEqual(self.ks.get(MAIN), TOKEN)
                self.assertIsNone(self.ks.get(PENDING))
        self.assert_no_secret_leak(TOKEN)

    def test_rotate_bad_response_not_stored(self):
        self.connect()
        self.expire_in(5)
        other = "imp_is_" + "9" * 24 + ".tok_Other1." + "O" * 43
        self.srv.rotate_script = [(200, {"stream_id": STREAM_ID, "token": other})]
        code, out = self.cli("run-once")
        self.assertEqual(code, 0, out)
        self.assertIn("응답 모양이 맞지 않아", out)
        self.assertIsNone(self.ks.get(PENDING))
        self.assertEqual(self.ks.get(MAIN), TOKEN)
        self.assert_no_secret_leak(TOKEN, other)

    def test_no_rotate_when_auth_halted_or_no_upload(self):
        self.connect()
        self.expire_in(5)
        code, out = self.cli("run-once", "--no-upload")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.rotate_calls(), [])
        self.srv.revoked = True
        path = os.path.join(self.th.root, "likes.jsonl")
        write_jsonl(path, [synth_row(1)])
        cfg = _config.load(self.th.paths)
        cfg["adapters"]["likes"].update({"enabled": True, "input_path": path, "provider_code": "synthnet",
                                         "include_kinds": ["kindA"]})
        _config.save(self.th.paths, cfg)
        code, out = self.cli("run-once")
        self.assertEqual(code, 3, out)
        self.assertEqual(self.rotate_calls(), [])

    def test_disconnect_removes_pending(self):
        self.connect()
        self.ks.set(PENDING, "imp_" + STREAM_ID + ".tok_Pend01." + "P" * 43)
        code, out = self.cli("disconnect")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.ks.get(PENDING))
        self.assertIsNone(self.ks.get(MAIN))

    # ---- M3 계정 전환 ------------------------------------------------------------
    def test_connect_other_account_drops_old_tokens(self):
        self.connect()
        self.ks.set(PENDING, "imp_" + STREAM_ID + ".tok_Pend01." + "P" * 43)
        sid2 = "is_" + "7" * 24
        tok2 = "imp_" + sid2 + ".tok_Acct2x." + "T" * 43
        self.srv.token = tok2
        self.srv.device_info = dict(self.srv.device_info, stream_id=sid2)
        self.kw["stdin"] = io.StringIO(tok2 + "\n")       # 앱이 sidecar stdin 으로 넘기는 경로
        self.kw["getpass_fn"] = lambda prompt: self.fail("getpass used")
        code, out = self.cli("connect", "--server", self.srv.url, "--token-stdin")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.ks.get(MAIN))
        self.assertIsNone(self.ks.get(PENDING))
        self.assertEqual(self.ks.get(_config.token_account(sid2)), tok2)
        self.assertIsNotNone(self.ks.get(_config.hmac_account(NAMESPACE)))   # 같은 키 공간 HMAC 키는 유지
        self.assertEqual(_config.load(self.th.paths)["source_instance_id"], sid2)
        self.assert_no_secret_leak(TOKEN, tok2)

    def test_reconnect_same_account_clears_pending(self):
        self.connect()
        self.ks.set(PENDING, "imp_" + STREAM_ID + ".tok_Pend01." + "P" * 43)
        self.connect()
        self.assertIsNone(self.ks.get(PENDING))
        self.assertEqual(self.ks.get(MAIN), TOKEN)


class RotateDueTest(unittest.TestCase):
    def test_due_rules(self):
        now = _dt.datetime(2026, 11, 2, 12, 0, tzinfo=osutil.KST)
        due = cli._rotate_due
        self.assertFalse(due({}, now))
        self.assertFalse(due({"token_expires_at": "nonsense"}, now))
        self.assertFalse(due({"token_expires_at": "2026-11-20T00:00:00"}, now))     # 시간대 없음 = 모름
        self.assertTrue(due({"token_expires_at": "2026-11-20T00:00:00+09:00"}, now))
        self.assertTrue(due({"token_expires_at": "2026-11-20T00:00:00Z"}, now))      # 3.9 Z 처리
        self.assertTrue(due({"token_expires_at": "2026-10-01T00:00:00+09:00"}, now))  # 이미 지남
        self.assertFalse(due({"token_expires_at": "2027-01-18T00:00:00+09:00"}, now))


if __name__ == "__main__":
    unittest.main()
