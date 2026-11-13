"""AI 연결(명세 2026-11-13 1.3) — 공급자 CLI 찾기, 인증 상태, 로그인 띄우기와 터미널 대체, 로컬 끊기 표시, ai-* 하위 명령.
상태 낱말은 서버 계약 hello.ai_links 와 같다(linked, signed_out, off, missing).
실제 claude, codex 는 부르지 않는다(가짜 실행 파일과 가짜 run, popen, sleep, clock)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest

from agent import ai_connection, config as _config
from agent.tests import helpers

LINKED = {"state": "linked", "code": None}


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

    def status(self, rc, out=b"", provider="claude", cfg=None):
        return ai_connection.status(provider, cfg or self.cfg, self.home, run=self.run_with(rc, out),
                                    env={"HOME": self.root}, path_value="", platform="win32", user_home=self.root)

    def test_exit_code_and_auth_method_decide_the_state(self):
        self.assertEqual(self.status(0, b'{"loggedIn":true,"authMethod":"claude.ai","email":"x@example.invalid"}'), LINKED)
        self.assertEqual(self.status(0, b'{"authMethod":"oauth_token"}'), LINKED)
        self.assertEqual(self.status(0, b'{"authMethod":"api_key"}'), {"state": "signed_out", "code": "unsupported-auth"})
        self.assertEqual(self.status(0, b'{"authMethod":"none"}'), {"state": "signed_out", "code": None})
        self.assertEqual(self.status(1, b'{"authMethod":"none"}'), {"state": "signed_out", "code": None})
        self.assertEqual(self.status(0, b"not json"), {"state": "signed_out", "code": "status-unreadable"})
        self.assertEqual(self.status(2), {"state": "signed_out", "code": "status-exit-2"})
        argv, kw = self.calls[0]
        self.assertEqual(argv, [self.cli, "auth", "status", "--json"])
        self.assertEqual(kw["cwd"], self.home)
        self.assertIs(kw["shell"], False)
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)

    def test_codex_exit_zero_is_linked_and_its_output_is_not_read(self):
        codex = fake_cli(self.root, "codex")
        cfg = {"summary": {"codex_cli_path": codex}}
        self.assertEqual(self.status(0, b"Logged in as someone", provider="codex", cfg=cfg), LINKED)
        self.assertEqual(self.status(1, provider="codex", cfg=cfg)["state"], "signed_out")
        self.assertEqual(self.calls[0][0], [codex, "login", "status"])

    def test_runner_failure_is_a_state_not_an_exception(self):
        def boom(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)
        self.assertEqual(ai_connection.status("claude", self.cfg, self.home, run=boom, env={}, path_value="",
                                              platform="win32", user_home=self.root),
                         {"state": "signed_out", "code": "status-timeout"})

    def test_missing_cli_and_local_off_do_not_run_anything(self):
        cfg = {"summary": {"cli_path": None}}
        self.assertEqual(ai_connection.status("claude", cfg, self.home, run=self.run_with(0), env={}, path_value="",
                                              platform="win32", user_home=self.root), {"state": "missing", "code": None})
        ai_connection.set_off(self.home, "claude", True)
        self.assertEqual(self.status(0, b'{"authMethod":"claude.ai"}'), {"state": "off", "code": None})
        self.assertEqual(self.calls, [])

    def test_a_cli_chat_would_refuse_is_missing_and_never_runs(self):
        # A group-writable folder fails chat_claude.resolve_cli_path; status must agree with chat instead of saying linked.
        loose = os.path.join(self.root, "loose")
        os.makedirs(loose)
        cli = fake_cli(loose)
        os.chmod(os.path.dirname(cli), 0o777)
        cfg = {"summary": {"cli_path": cli}}
        self.assertEqual(self.status(0, b'{"authMethod":"claude.ai"}', cfg=cfg), {"state": "missing", "code": "untrusted-cli"})
        self.assertEqual(self.calls, [])
        self.assertFalse(ai_connection.trusted("claude", cli))
        self.assertTrue(ai_connection.trusted("claude", self.cli))

    def test_codex_gets_the_same_trust_check_and_an_untrusted_codex_never_runs(self):
        loose = os.path.join(self.root, "loose-codex")
        os.makedirs(loose)
        codex = fake_cli(loose, "codex")
        os.chmod(os.path.dirname(codex), 0o777)
        self.assertFalse(ai_connection.trusted("codex", codex))
        self.assertFalse(ai_connection.trusted("other", self.cli))
        self.assertEqual(self.status(0, provider="codex", cfg={"summary": {"codex_cli_path": codex}}),
                         {"state": "missing", "code": "untrusted-cli"})
        self.assertEqual(self.calls, [])
        self.assertTrue(ai_connection.trusted("codex", fake_cli(self.root, "codex")))

    def test_probe_false_finds_and_checks_the_file_but_does_not_run_it(self):
        codex = fake_cli(self.root, "codex")
        cfg = {"summary": {"cli_path": self.cli, "codex_cli_path": codex}}
        states = ai_connection.statuses(cfg, self.home, probe=("claude",), run=self.run_with(0, b'{"authMethod":"claude.ai"}'),
                                        env={}, path_value="", platform="win32", user_home=self.root)
        self.assertEqual(states, {"claude": LINKED, "codex": {"state": "signed_out", "code": "unchecked"}})
        self.assertEqual([c[0][0] for c in self.calls], [self.cli], "codex was not run")
        ai_connection.set_off(self.home, "codex", True)
        self.assertEqual(ai_connection.status("codex", cfg, self.home, probe=False, run=self.run_with(0), env={}, path_value="",
                                              platform="win32", user_home=self.root), {"state": "off", "code": None})
        self.assertEqual(ai_connection.status("codex", {"summary": {}}, self.home, probe=False, off=frozenset(), run=self.run_with(0),
                                              env={}, path_value="", platform="win32", user_home=self.root),
                         {"state": "missing", "code": None})
        self.assertEqual(len(self.calls), 1)

    def test_links_keep_only_provider_names_and_state_words(self):
        self.assertEqual(ai_connection.links({"claude": LINKED, "codex": {"state": "weird"}, "other": LINKED}),
                         {"claude": "linked"})
        self.assertEqual(ai_connection.link("signed_out", "has space"), {"state": "signed_out", "code": None})

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


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class LoginTest(unittest.TestCase):
    """Main's rule (2026-11-13): no TTY, check the status every 3 seconds for at most 5 minutes; a login that fails at
    once is opened again in the system terminal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.cli = fake_cli(self.root)
        self.cfg = {"summary": {"cli_path": self.cli}}
        self.clock = Clock()
        self.started = []

    def child(self, exits_at=None, rc=0):
        test = self

        class Child:
            def __init__(self, argv, **kw):
                test.started.append((argv, kw))
                self.killed = False
                self.is_login = argv[0] == test.cli
            def poll(self):
                if not self.is_login or self.killed:
                    return -9 if self.killed else 0
                return rc if exits_at is not None and test.clock() >= exits_at else None
            def kill(self):
                self.killed = True
            def wait(self, timeout=None):
                return 0
        return Child

    def login(self, answers, popen, platform="linux"):
        def run(argv, **kw):
            return answers.pop(0) if len(answers) > 1 else answers[0]
        return ai_connection.login("claude", self.cfg, self.root, popen=popen, env={"HOME": self.root}, run=run,
                                   sleep=self.clock.sleep, clock=self.clock, platform=platform, path_value="",
                                   user_home=self.root)

    def test_polls_every_3_seconds_until_linked_without_reading_login_output(self):
        state = self.login([Done(1), Done(1), Done(0, b'{"authMethod":"claude.ai"}')], self.child())
        self.assertEqual(state, LINKED)
        self.assertEqual(self.clock(), 9.0)
        argv, kw = self.started[0]
        self.assertEqual(argv, [self.cli, "auth", "login", "--claudeai"])
        self.assertEqual((kw["stdout"], kw["stderr"], kw["shell"]), (subprocess.DEVNULL, subprocess.DEVNULL, False))

    def test_gives_up_after_5_minutes_and_kills_the_login(self):
        Child = self.child()
        state = self.login([Done(1)], Child)
        self.assertEqual(state, {"state": "signed_out", "code": "login-unfinished"})
        self.assertEqual(self.clock(), float(ai_connection.LOGIN_WAIT))
        self.assertEqual(len(self.started), 1)

    def test_a_login_that_fails_at_once_reopens_in_the_mac_terminal(self):
        state = self.login([Done(1), Done(1), Done(0, b'{"authMethod":"claude.ai"}')], self.child(exits_at=1, rc=1),
                           platform="darwin")
        self.assertEqual(state, LINKED)
        terminal = self.started[1][0]
        self.assertEqual(terminal[:3], ["/usr/bin/open", "-a", "Terminal"])
        script = terminal[3]
        self.assertEqual(os.path.dirname(script), self.root)
        with open(script) as f:
            self.assertEqual(f.read(), f"#!/bin/sh\nexec {self.cli} auth login --claudeai\n")
        self.assertEqual(os.stat(script).st_mode & 0o777, 0o700)

    def test_windows_terminal_runs_the_exe_in_a_new_console_without_cmd_and_linux_has_no_terminal(self):
        exe = fake_cli(self.root, "claude.exe")
        self.cli, self.cfg = exe, {"summary": {"cli_path": exe}}
        self.login([Done(1), Done(1), Done(0, b'{"authMethod":"claude.ai"}')], self.child(exits_at=1, rc=1),
                   platform="win32")
        argv, kw = self.started[1]
        self.assertEqual(argv, [exe, "auth", "login", "--claudeai"])
        self.assertNotIn("cmd", argv)
        self.assertEqual(kw["creationflags"], ai_connection.CREATE_NEW_CONSOLE)
        self.assertEqual((kw["shell"], kw["cwd"], kw["env"]), (False, self.root, {"HOME": self.root}))
        self.assertNotIn("stdin", kw, "the new console keeps its own input for the login")
        self.started.clear()
        self.clock.t = 0
        # A .cmd/.bat would go through cmd again: no terminal, the login stays unfinished
        bat = fake_cli(self.root, "claude.cmd")
        self.cli, self.cfg = bat, {"summary": {"cli_path": bat}}
        state = self.login([Done(1)], self.child(exits_at=1, rc=1), platform="win32")
        self.assertEqual(state, {"state": "signed_out", "code": "login-unfinished"})
        self.assertEqual(len(self.started), 1)
        self.started.clear()
        self.clock.t = 0
        state = self.login([Done(1)], self.child(exits_at=1, rc=1), platform="linux")
        self.assertEqual(state, {"state": "signed_out", "code": "login-unfinished"})
        self.assertEqual(len(self.started), 1)
        self.assertLess(self.clock(), 10)

    def test_a_login_that_ends_without_linking_stops_waiting(self):
        state = self.login([Done(1)], self.child(exits_at=20, rc=0))
        self.assertEqual(state["state"], "signed_out")
        self.assertLess(self.clock(), 30)


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
        self.assertEqual(json.loads(out)["ai"]["claude"], LINKED)
        self.assertNotIn("example.invalid", out)
        self.assertEqual(_config.load(self.th.paths)["summary"]["cli_path"], self.cli)

    def test_ai_connect_clears_off_and_logs_in_only_when_signed_out(self):
        ai_connection.set_off(self.th.home, "claude", True)
        logins = []
        clock = Clock()

        class Child:
            def __init__(self, argv, **kw):
                logins.append(argv)
            def poll(self):
                return None
            def kill(self):
                pass
            def wait(self, timeout=None):
                return 0

        answers = [Done(1), Done(0, b'{"authMethod":"claude.ai"}')]
        code, out = helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "claude"],
                                    ai_kw=self.ai_kw(run=lambda argv, **kw: answers.pop(0) if len(answers) > 1 else answers[0],
                                                     popen=Child, sleep=clock.sleep, clock=clock))
        self.assertEqual((code, json.loads(out)), (0, {"ai": {"claude": LINKED}}))
        self.assertEqual(logins, [[self.cli, "auth", "login", "--claudeai"]])
        self.assertEqual(ai_connection.read_off(self.th.home), frozenset())

        code, out = helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "claude"],
                                    ai_kw=self.ai_kw(run=lambda argv, **kw: Done(0, b'{"authMethod":"claude.ai"}'),
                                                     popen=Child))
        self.assertEqual(json.loads(out), {"ai": {"claude": LINKED}})
        self.assertEqual(len(logins), 1)

    def test_codex_is_run_only_when_the_user_connects_it_while_not_ready(self):
        from agent import cli
        codex = fake_cli(os.path.dirname(os.path.dirname(self.cli)), "codex")
        runs = []
        def run(argv, **kw):
            runs.append(argv)
            return Done(0, b'{"authMethod":"claude.ai"}')
        self.assertFalse(cli.CHAT_CODEX_PROVIDER_READY)
        self.assertEqual(cli.auto_probe(), ("claude",))
        code, out = helpers.run_cli(["--home", self.th.home, "ai-status"], ai_kw=self.ai_kw(run=run))
        self.assertEqual(json.loads(out)["ai"]["codex"], {"state": "signed_out", "code": "unchecked"})
        self.assertEqual(runs, [[self.cli, "auth", "status", "--json"]], "ai-status did not run codex")
        runs.clear()
        code, out = helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "codex"], ai_kw=self.ai_kw(run=run))
        self.assertEqual((code, json.loads(out)), (0, {"ai": {"codex": LINKED}}))
        self.assertEqual(runs, [[codex, "login", "status"]], "the user press runs codex login status")
        from unittest.mock import patch
        with patch.object(cli, "CHAT_CODEX_PROVIDER_READY", True):
            self.assertEqual(cli.auto_probe(), ("claude", "codex"))

    def test_ai_disconnect_marks_off_without_running_the_cli(self):
        def run(argv, **kw):
            raise AssertionError("no CLI call")
        code, out = helpers.run_cli(["--home", self.th.home, "ai-disconnect", "--provider", "claude"],
                                    ai_kw=self.ai_kw(run=run))
        self.assertEqual((code, json.loads(out)), (0, {"ai": {"claude": {"state": "off", "code": None}}}))
        code, out = helpers.run_cli(["--home", self.th.home, "ai-status"], ai_kw=self.ai_kw(run=run))
        self.assertEqual(json.loads(out)["ai"]["claude"]["state"], "off")

    def test_bad_provider_is_a_usage_error(self):
        with self.assertRaises(SystemExit):
            helpers.run_cli(["--home", self.th.home, "ai-connect", "--provider", "other"])


if __name__ == "__main__":
    unittest.main()
