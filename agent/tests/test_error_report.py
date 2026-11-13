"""오류 자동 보고(명세 2026-11-13 1.4) — 에이전트 쪽 본문 꼴과 run-once 멈춤, 실패 보고. 본문에 경로, 토큰, 원문이 없다."""
from __future__ import annotations

import datetime as _dt
import json
import os
import unittest

from agent import AGENT_VERSION, error_report
from agent.tests import helpers


class BuildTest(unittest.TestCase):
    def test_only_fixed_fields_and_known_stages(self):
        now = _dt.datetime(2026, 11, 13, 3, 4, 5, 678, tzinfo=_dt.timezone.utc)
        body = error_report.build("run-once/halt", "halt-policy", now=now, platform="darwin")
        self.assertEqual(body, {"source": "agent", "stage": "run-once/halt", "code": "halt-policy",
                                "app_version": AGENT_VERSION, "os": "mac", "occurred_at": "2026-11-13T03:04:05Z"})
        self.assertEqual(error_report.build("run-once/failed", "run-error", platform="win32")["os"], "win")
        for stage, code in (("other/stage", "x"), ("run-once/halt", "/Users/someone/file"), ("run-once/halt", "A B"),
                            ("run-once/halt", "x" * 41), ("run-once/halt", None)):
            with self.subTest(stage=stage, code=code):
                self.assertIsNone(error_report.build(stage, code))

    def test_send_posts_once_with_the_device_token_and_never_raises(self):
        seen = []

        class Res:
            status = 202
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        class Opener:
            def open(self, req, timeout=None):
                seen.append((req.full_url, req.get_header("Authorization"), json.loads(req.data), timeout))
                return Res()

        self.assertTrue(error_report.send("https://crm.example.invalid", "tok-synthetic", "run-once/halt", "halt-policy",
                                          opener=Opener()))
        url, auth, body, timeout = seen[0]
        self.assertEqual((url, auth, timeout), ("https://crm.example.invalid" + error_report.REPORT_PATH,
                                                "Bearer tok-synthetic", error_report.TIMEOUT))
        self.assertEqual(set(body), {"source", "stage", "code", "app_version", "os", "occurred_at"})

        class Broken:
            def open(self, req, timeout=None):
                raise OSError("synthetic network failure")
        self.assertFalse(error_report.send("https://crm.example.invalid", "tok", "run-once/halt", "halt-x", opener=Broken()))
        self.assertFalse(error_report.send("http://crm.example.invalid", "tok", "run-once/halt", "halt-x", opener=Opener()))
        self.assertFalse(error_report.send("https://crm.example.invalid", "", "run-once/halt", "halt-x", opener=Opener()))
        self.assertEqual(len(seen), 1)


class RunOnceReportTest(unittest.TestCase):
    def setUp(self):
        self.th = helpers.TempHome()
        self.addCleanup(self.th.cleanup)
        self.srv = helpers.FakeImportServer()
        self.addCleanup(self.srv.close)
        self.ks = helpers.MemoryKeyStore()
        self.reports = []
        self.kw = dict(ks_factory=lambda service: self.ks, getpass_fn=lambda prompt: helpers.TOKEN,
                       report_fn=lambda *a: self.reports.append(a))

    def cli(self, *argv):
        return helpers.run_cli(["--home", self.th.home] + list(argv), **self.kw)

    def test_a_failed_run_reports_its_kind_only(self):
        code, _ = self.cli("connect", "--server", self.srv.url)
        self.assertEqual(code, 0)
        from agent import runner
        orig = runner.run_once
        def boom(*a, **k):
            raise runner.RunError("/Users/someone/secret-path.jsonl 를 읽지 못했어요")
        runner.run_once = boom
        try:
            code, out = self.cli("run-once")
        finally:
            runner.run_once = orig
        self.assertEqual(code, 1)
        self.assertEqual(len(self.reports), 1)
        server, token, stage, err = self.reports[0]
        self.assertEqual((server, token, stage, err), (self.srv.url, helpers.TOKEN, "run-once/failed", "run-error"))
        self.assertNotIn("secret-path", json.dumps(self.reports))

    def test_a_halt_reports_but_an_auth_halt_does_not(self):
        code, _ = self.cli("connect", "--server", self.srv.url)
        self.assertEqual(code, 0)
        from agent import runner
        orig = runner.run_once
        for stopped, expected in (("policy-halted", [("run-once/halt", "halt-policy")]), ("auth", [])):
            with self.subTest(stopped=stopped):
                self.reports.clear()
                runner.run_once = lambda *a, s=stopped, **k: {"upload": {"stopped": s}}
                try:
                    code, _ = self.cli("run-once", "--no-rotate")
                finally:
                    runner.run_once = orig
                self.assertEqual(code, 3)
                self.assertEqual([r[2:] for r in self.reports], expected)

    def test_not_connected_sends_nothing(self):
        code, _ = self.cli("run-once")
        self.assertEqual(self.reports, [])


if __name__ == "__main__":
    unittest.main()
