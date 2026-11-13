"""오류 자동 보고(명세 2026-11-13 1.4) — 에이전트 쪽 본문 꼴과 run-once 멈춤, 실패 보고. 본문에 경로, 토큰, 원문이 없다."""
from __future__ import annotations

import datetime as _dt
import json
import os
import unittest

from agent import AGENT_VERSION, error_report
from agent.tests import helpers


class BuildTest(unittest.TestCase):
    def test_only_fixed_fields_and_known_stages_and_bad_codes_become_unknown(self):
        now = _dt.datetime(2026, 11, 13, 3, 4, 5, 678, tzinfo=_dt.timezone.utc)
        body = error_report.build("run-once/halt", "halt-policy", now=now, platform="darwin")
        self.assertEqual(body, {"source": "agent", "stage": "run-once/halt", "code": "halt-policy",
                                "app_version": AGENT_VERSION, "os": "mac", "occurred_at": "2026-11-13T03:04:05Z",
                                "count": 1})
        self.assertEqual(error_report.build("run-once/failed", "run-error", platform="win32")["os"], "win")
        self.assertEqual(error_report.build("run-once/failed", "run-error", platform="linux")["os"], "other")
        self.assertIsNone(error_report.build("other/stage", "x"))
        for code in ("/srv/someone/file", "A B", "x" * 49, None, "a.b"):
            with self.subTest(code=code):
                self.assertEqual(error_report.build("run-once/halt", code)["code"], "unknown")
        self.assertEqual(error_report.build("run-once/halt", "HTTP-503")["code"], "HTTP-503")
        for stage in error_report.STAGES:
            self.assertTrue(error_report.STAGE.fullmatch(stage), stage)
        self.assertLessEqual(len(json.dumps(body).encode()), 2048)

    def test_send_posts_with_the_device_token_and_retries_once_on_network_or_5xx_only(self):
        import urllib.error
        seen = []

        class Res:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def opener(*outcomes):
            class Opener:
                def open(self, req, timeout=None):
                    seen.append((req.full_url, req.get_header("Authorization"), json.loads(req.data), timeout))
                    outcome = outcomes[min(len(seen) - 1, len(outcomes) - 1)]
                    if isinstance(outcome, BaseException):
                        raise outcome
                    return Res()
            return Opener()

        self.assertTrue(error_report.send("https://crm.example.invalid", "tok-synthetic", "run-once/halt", "halt-policy",
                                          opener=opener(None)))
        url, auth, body, timeout = seen[0]
        self.assertEqual((url, auth, timeout), ("https://crm.example.invalid/api/device/error-reports",
                                                "Bearer tok-synthetic", error_report.TIMEOUT))
        self.assertEqual(set(body), {"source", "stage", "code", "app_version", "os", "occurred_at", "count"})
        http = lambda code: urllib.error.HTTPError("https://x", code, "m", {}, None)
        for outcomes, ok, tries in (((OSError("down"), None), True, 2), ((http(503), http(503)), False, 2),
                                    ((http(429),), False, 1), ((http(400),), False, 1), ((http(401),), False, 1)):
            with self.subTest(outcomes=outcomes):
                seen.clear()
                self.assertEqual(error_report.send("https://crm.example.invalid", "tok", "run-once/halt", "halt-x",
                                                   opener=opener(*outcomes)), ok)
                self.assertEqual(len(seen), tries)
        seen.clear()
        self.assertFalse(error_report.send("http://crm.example.invalid", "tok", "run-once/halt", "halt-x", opener=opener(None)))
        self.assertFalse(error_report.send("https://crm.example.invalid", "", "run-once/halt", "halt-x", opener=opener(None)))
        self.assertEqual(seen, [])


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
            raise runner.RunError("/srv/someone/secret-path.jsonl 를 읽지 못했어요")
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
