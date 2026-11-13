"""AI 연결(명세 2026-11-13 1.3) — 공급자 CLI 찾기, 인증 상태, 로그인 띄우기, 로컬 끊기 표시, ai-* 하위 명령.
실제 claude, codex 는 부르지 않는다(가짜 실행 파일과 가짜 run, popen)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest

from agent import ai_connection, config as _config
from agent.tests import helpers


def fake_cli(root, name="claude"):
    path = os.path.join(root, "bin", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, 0o755)
    return path


class Done:
    def __init__(self, rc, out=b""):
        self.returncode, self.stdout = rc, out


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def test_finds_in_path_then_standard_dirs_and_skips_shims(self):
        cli = fake_cli(self.root)
        self.assertEqual(ai_connection.discover("claude", path_value=os.path.dirname(cli), platform="linux",
                                                user_home=self.root), cli)
        # Not on PATH (an app opened from the Finder): ~/.local/bin is a standard place.
        local = os.path.join(self.root, ".local", "bin")
        os.makedirs(local)
        os.symlink(cli, os.path.join(local, "claude"))
        self.assertEqual(ai_connection.discover("claude", path_value="", platform="darwin", user_home=self.root), cli)
        shim = os.path.join(self.root, ".cmuxterm", "cmux-cli-shims", "x")
        os.makedirs(shim)
        fake_cli(os.path.dirname(shim), "x")
        self.assertIsNone(ai_connection.discover("claude", path_value=shim + os.pathsep + "relative", platform="win32",
                                                 user_home=os.path.join(self.root, "nobody")))

    def test_unknown_provider_and_missing_binary(self):
        self.assertIsNone(ai_connection.discover("other", path_value="", platform="linux", user_home=self.root))
        self.assertIsNone(ai_connection.discover("codex", path_value="", platform="win32", user_home=self.root))


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.home = os.path.join(self.root, "agent-home")
        os.makedirs(self.home)
        self.cli = fake_cli(self.root)
        self.cfg = {"summary": {"cli_path": self.cli}}
        self.calls = []

    def run_with(self, rc, out=b""):
        def run(argv, **kw):
            self.calls.append((argv, kw))
            return Done(rc, out)
        return run

    def status(self, rc, out=b"", **kw):
        return ai_connection.status("claude", self.cfg, self.home, run=self.run_with(rc, out), env={"HOME": self.root},
                                    path_value="", platform="win32", user_home=self.root, **kw)

    def test_exit_code_and_auth_method_decide_the_state(self):
        self.assertEqual(self.status(0, b'{"loggedIn":true,"authMethod":"claude.ai","email":"x@example.invalid"}'), "ready")
        self.assertEqual(self.status(0, b'{"authMethod":"oauth_token"}'), "ready")
        self.assertEqual(self.status(0, b'{"authMethod":"api_key"}'), "unsupported")
        self.assertEqual(self.status(0, b'{"authMethod":"none"}'), "signed-out")
        self.assertEqual(self.status(1, b'{"authMethod":"none"}'), "signed-out")
        self.assertEqual(self.status(0, b"not json"), "error")
        self.assertEqual(self.status(2), "error")
        argv, kw = self.calls[0]
        self.assertEqual(argv, [self.cli, "auth", "status", "--json"])
        self.assertEqual(kw["cwd"], self.home)
        self.assertIs(kw["shell"], False)
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)

    def test_runner_failure_is_an_error_not_an_exception(self):
        def boom(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)
        self.assertEqual(ai_connection.status("claude", self.cfg, self.home, run=boom, env={}, path_value="",
                                              platform="win32", user_home=self.root), "error")

    def test_missing_cli_and_local_off_do_not_run_anything(self):
        cfg = {"summary": {"cli_path": None}}
        self.assertEqual(ai_connection.status("claude", cfg, self.home, run=self.run_with(0), env={}, path_value="",
                                              platform="win32", user_home=self.root), "missing")
        ai_connection.set_off(self.home, "claude", True)
        self.assertEqual(self.status(0, b'{"authMethod":"claude.ai"}'), "off")
        self.assertEqual(self.calls, [])

    def test_env_is_the_chat_allow_list_without_api_keys(self):
        env = ai_connection.clean_env({"HOME": "/h", "PATH": "/p", "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k",
                                       "SOMETHING": "x"})
        self.assertEqual(env, {"HOME": "/h", "PATH": "/p"})


class OffMarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def test_off_and_on_round_trip(self):
        self.assertEqual(ai_connection.read_off(self.home), frozenset())
        ai_connection.set_off(self.home, "claude", True)
        self.assertEqual(ai_connection.read_off(self.home), frozenset({"claude"}))
        ai_connection.set_off(self.home, "claude", False)
        self.assertEqual(ai_connection.read_off(self.home), frozenset())
        with self.assertRaises(ValueError):
            ai_connection.set_off(self.home, "other", True)

    def test_a_broken_mark_reads_as_all_off(self):
        for raw in ("{", '{"off": ["other"]}', '{"off": "claude"}', "[]"):
            with self.subTest(raw=raw):
                with open(os.path.join(self.home, ai_connection.USE_FILE), "w") as f:
                    f.write(raw)
                self.assertEqual(ai_connection.read_off(self.home), frozenset(ai_connection.PROVIDERS))
        ai_connection.set_off(self.home, "claude", False)   # reconnecting one provider leaves the others off
        self.assertEqual(ai_connection.read_off(self.home), frozenset({"codex"}))


class LoginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.cli = fake_cli(self.root)
        self.cfg = {"summary": {"cli_path": self.cli}}

    def test_login_runs_the_provider_login_without_reading_output_then_rechecks(self):
        started = []

        class Child:
            def __init__(self, argv, **kw):
                started.append((argv, kw))
            def wait(self, timeout=None):
                return 0
            def kill(self):
                raise AssertionError("not killed")

        state = ai_connection.login("claude", self.cfg, self.root, popen=Child, env={"HOME": self.root},
                                    run=lambda argv, **kw: Done(0, b'{"authMethod":"claude.ai"}'),
                                    path_value="", platform="win32", user_home=self.root)
        self.assertEqual(state, "ready")
        argv, kw = started[0]
        self.assertEqual(argv, [self.cli, "auth", "login", "--claudeai"])
        self.assertEqual((kw["stdout"], kw["stderr"], kw["shell"]), (subprocess.DEVNULL, subprocess.DEVNULL, False))

    def test_login_timeout_kills_the_child(self):
        killed = []

        class Child:
            def __init__(self, argv, **kw):
                pass
            def wait(self, timeout=None):
                if not killed:
                    raise subprocess.TimeoutExpired("claude", timeout)
                return -9
            def kill(self):
                killed.append(True)

        state = ai_connection.login("claude", self.cfg, self.root, popen=Child, env={}, timeout=1,
                                    run=lambda argv, **kw: Done(1), path_value="", platform="win32", user_home=self.root)
        self.assertEqual((state, killed), ("signed-out", [True]))


class CliCommandTest(unittest.TestCase):
    def setUp(self):
        self.th = helpers.TempHome()
        self.addCleanup(self.th.cleanup)
        helpers.connected_config(self.th, "http://127.0.0.1:9")
        self.cli = fake_cli(os.path.realpath(self.th.root))

    def ai_kw(self, **extra):
        return {"path_value": os.path.dirname(self.cli), "platform": "linux",
                "user_home": os.path.join(self.th.root, "user"), **extra}

    def test_ai_status_remembers_the_found_claude_and_prints_states_only(self):
        runs = []
        def run(argv, **kw):
            runs.append(argv)
            return Done(0, b'{"authMethod":"claude.ai","email":"person@example.invalid","orgName":"Org"}')
        code, out = helpers.run_cli(["--home", self.th.home, "ai-status"], ai_kw=self.ai_kw(run=run))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["ai"]["claude"], "ready")
        self.assertNotIn("example.invalid", out)
        self.assertEqual(_config.load(self.th.paths)["summary"]["cli_path"], self.cli)

    def test_ai_connect_clears_off_and_logs_in_only_when_signed_out(self):
        ai = __import__("agent.ai_connection", fromlist=["x"])
        ai.set_off(self.th.home, "claude", True)
        logins = []

        class Child:
            def __init__(self, argv, **kw):
                logins.append(argv)
            def wait(self, timeout=None):
                return 0

        answers = iter([Done(1), Done(0, b'{"authMethod":"claude.ai"}')])
        code, out = helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "claude"],
                                    ai_kw=self.ai_kw(run=lambda argv, **kw: next(answers), popen=Child))
        self.assertEqual((code, json.loads(out)), (0, {"ai": {"claude": "ready"}}))
        self.assertEqual(logins, [[self.cli, "auth", "login", "--claudeai"]])
        self.assertEqual(ai.read_off(self.th.home), frozenset())

        code, out = helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "claude"],
                                    ai_kw=self.ai_kw(run=lambda argv, **kw: Done(0, b'{"authMethod":"claude.ai"}'),
                                                     popen=Child))
        self.assertEqual(json.loads(out), {"ai": {"claude": "ready"}})
        self.assertEqual(len(logins), 1)

    def test_ai_disconnect_marks_off_without_running_the_cli(self):
        def run(argv, **kw):
            raise AssertionError("no CLI call")
        code, out = helpers.run_cli(["--home", self.th.home, "ai-disconnect", "--provider", "claude"],
                                    ai_kw=self.ai_kw(run=run))
        self.assertEqual((code, json.loads(out)), (0, {"ai": {"claude": "off"}}))
        code, out = helpers.run_cli(["--home", self.th.home, "ai-status"], ai_kw=self.ai_kw(run=run))
        self.assertEqual(json.loads(out)["ai"]["claude"], "off")

    def test_bad_provider_is_a_usage_error(self):
        with self.assertRaises(SystemExit):
            helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "other"])


if __name__ == "__main__":
    unittest.main()
