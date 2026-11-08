"""Fixture-only contract tests for the disabled Codex provider candidate."""
import json
import hashlib
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agent import chat_codex
from agent.chat_launch_authority import AUTH_PATH, LaunchAuthorizationClient
from agent import chat, wsclient
from agent.tests.wsfake import FakeWsServer


class Launch:
    user_id = "user-synthetic"
    device_id = "device-synthetic"
    session_id = "session-synthetic"
    provider = "codex"
    model = "gpt-6.1-sol"
    consent_id = "consent-synthetic"
    issuer = "fixture-issuer"
    signature = "fixture-signature-that-is-not-a-real-signature"
    expires_at = time.time() + 600
    cli_path = ""
    cli_sha256 = ""
    codex_home = ""
    gateway_path = "/fixture/mycrm-gateway"
    gateway_args = []
    config = {
        "mcp_servers": {
            "my_crm": {
                "command": "/fixture/mycrm-gateway",
                "args": [],
                "enabled": True,
                "required": True,
                "enabled_tools": ["find_records", "update_record"],
                "disabled_tools": ["trash_purge", "purge"],
            }
        }
    }
    env = {}

    def current(self):
        return True


class FixtureVerifier:
    """Test double only; never an authentication authority for an application."""
    def verify_codex_grant(self, grant):
        return grant.issuer == "fixture-issuer" and grant.signature.startswith("fixture-signature")


class FixtureSupervisor(chat_codex.CodexProcessSupervisor):
    """Synthetic supervisor only; not suitable for running the real Codex CLI."""
    def __init__(self, *, popen=None, child_pid_file=None):
        import subprocess
        self.popen = popen or subprocess.Popen
        self.child_pid_file = child_pid_file
        self.spawned = []
        self.cleaned = []

    def spawn(self, argv, **kwargs):
        if "start_new_session" in kwargs or "preexec_fn" in kwargs:
            raise chat_codex.ProcessContainmentUnavailable("session-setup-owned-by-supervisor")
        kwargs.update({"start_new_session": True, "shell": False, "close_fds": True})
        proc = self.popen(argv, **kwargs)
        self.spawned.append(proc)
        return proc

    def _fixture_child_cleanup(self):
        if not self.child_pid_file or not os.path.exists(self.child_pid_file):
            return
        with open(self.child_pid_file, encoding="utf-8") as handle:
            child_pid = int(handle.read())
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.cleaned.append(child_pid)

    def finish(self, proc, timeout):
        rc = proc.wait(timeout=timeout)
        self._fixture_child_cleanup()
        return rc, True

    def terminate_tree(self, proc):
        import subprocess
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        self._fixture_child_cleanup()


class CodexProviderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chat-codex-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.runtime = os.path.join(self.root, "runtime")
        self.cwd = os.path.join(self.root, "empty")
        os.mkdir(self.runtime, 0o700)
        os.mkdir(self.cwd, 0o700)
        self.capture = os.path.join(self.root, "argv.json")
        self.prompt_capture = os.path.join(self.root, "prompt.txt")
        self.child_pid_file = os.path.join(self.root, "child.pid")
        self.exe = os.path.join(self.root, "codex-fixture")
        self.launch = Launch()
        self.launch.config = json.loads(json.dumps(Launch.config))
        self.launch.env = {
            "HOME": self.root,
            "CODEX_HOME": os.path.join(self.root, ".codex"),
            "PATH": os.environ.get("PATH", "/usr/bin"),
        }
        os.mkdir(self.launch.env["CODEX_HOME"], 0o700)
        self.launch.codex_home = self.launch.env["CODEX_HOME"]
        self.launch.cwd = self.cwd
        self.launch.runtime_dir = self.runtime
        self.launch.gateway_path = self.launch.config["mcp_servers"]["my_crm"]["command"]
        self.launch.gateway_args = []
        self._fixture("success")

    def _fixture(self, mode):
        script = "#!/usr/bin/env python3\nimport json, pathlib, sys, time\n"
        script += f"mode={mode!r}\n"
        script += f"pathlib.Path({self.capture!r}).write_text(json.dumps(sys.argv[1:]))\n"
        script += "prompt=sys.stdin.read()\n"
        script += f"pathlib.Path({self.prompt_capture!r}).write_text(prompt)\n"
        script += "if mode == 'hang': time.sleep(30)\n"
        script += f"if mode == 'child':\n  child=__import__('subprocess').Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=__import__('subprocess').DEVNULL, stderr=__import__('subprocess').DEVNULL)\n  pathlib.Path({self.child_pid_file!r}).write_text(str(child.pid))\n"
        script += "if mode == 'error': print(json.dumps({'type':'error','message':'fixture-secret'}), flush=True); sys.exit(1)\n"
        script += "if mode in ('success','child'):\n"
        script += "  for obj in ({'type':'thread.started','thread_id':'0199a213-81c0-7800-8aa1-bbab2a035a53'}, {'type':'turn.started'}, {'type':'item.completed','item':{'type':'agent_message','text':'fixture reply'}}, {'type':'turn.completed'}): print(json.dumps(obj), flush=True)\n"
        with open(self.exe, "w", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(self.exe, 0o700)
        self.launch.cli_path = self.exe
        with open(self.exe, "rb") as handle:
            self.launch.cli_sha256 = hashlib.sha256(handle.read()).hexdigest()

    def provider(self, **overrides):
        kwargs = dict(cli_path=self.exe, model=self.launch.model, launch_context=self.launch,
                      launch_verifier=FixtureVerifier(),
                      process_supervisor=FixtureSupervisor(child_pid_file=self.child_pid_file), timeout=3.0)
        kwargs.update(overrides)
        return chat_codex.CodexProvider(**kwargs)

    def test_requires_verified_user_device_session_provider_model_grant(self):
        with self.assertRaises(chat_codex.CodexProviderUnavailable):
            chat_codex.CodexProvider(cli_path=self.exe, model=self.launch.model)
        with self.assertRaises(chat_codex.CodexProviderUnavailable):
            self.provider(launch_verifier=lambda _grant: False)
        with self.assertRaises(chat_codex.CodexProviderUnavailable):
            self.provider(process_supervisor=None)
        for field in ("user_id", "device_id", "session_id", "provider", "model"):
            saved = getattr(self.launch, field)
            setattr(self.launch, field, "")
            with self.assertRaises(chat_codex.CodexProviderUnavailable):
                self.provider()
            setattr(self.launch, field, saved)

    def test_server_factory_mints_codex_turn_from_exact_launch_authorization(self):
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat().replace("+00:00", "Z")
        response = {"authorized": True, "binding": {
            "user_id": "u_" + "a" * 24, "device_id": "is_" + "b" * 24,
            "session_id": "cs_" + "c" * 24, "turn_id": "ct_" + "d" * 24,
            "provider": "codex", "model": "gpt-6.1-sol", "grant_id": "grant_synthetic",
            "consent_challenge_id": "challenge_synthetic", "expires_at": expiry},
            "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read",
                      "mcp__my-crm__record_update": "write",
                      "mcp__my-crm__candidate_decide": "decide"}}
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(response).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token")
        client._opener = Opener()
        home = os.path.join(self.root, "app-home")
        codex_home = os.path.join(home, "codex-home")
        os.makedirs(codex_home, mode=0o700)
        os.chmod(home, 0o700); os.chmod(codex_home, 0o700)
        with patch.object(sys, "platform", "darwin"):
            factory = chat_codex.CodexProviderFactory(client, cli_path=self.exe,
                server_url="https://synthetic.invalid", agent_home=home, codex_home=codex_home,
                expected_device_id=response["binding"]["device_id"], models=("gpt-6.1-sol",),
                process_supervisor=FixtureSupervisor())
            provider = factory.create_turn(response["binding"]["session_id"], response["binding"]["turn_id"],
                                           AUTH_PATH, "codex", "gpt-6.1-sol")
        self.addCleanup(provider.close)
        context = provider.launch_context
        self.assertEqual((context.user_id, context.device_id, context.session_id, context.turn_id),
                         (response["binding"]["user_id"], response["binding"]["device_id"],
                          response["binding"]["session_id"], response["binding"]["turn_id"]))
        server = context.config["mcp_servers"]["my_crm"]
        self.assertEqual(server["command"], os.path.realpath(sys.executable))
        self.assertIn("agent.chat_mcp_bridge", server["args"])
        self.assertEqual(server["enabled_tools"], ["mcp__my-crm__find", "mcp__my-crm__read",
                                                   "mcp__my-crm__write", "mcp__my-crm__decide"])
        argv = chat_codex.build_argv(self.exe, "gpt-6.1-sol", context.config, context.cwd)
        approval_overrides = [item for item in argv if "approval_policy=" in item or "approval_mode=" in item]
        self.assertEqual(approval_overrides, [])
        self.assertTrue(any("mcp_servers.my_crm.enabled_tools=" in item for item in argv))
        self.assertFalse({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} & context.env.keys())
        self.assertEqual(context.env["CODEX_HOME"], os.path.realpath(codex_home))
        self.assertTrue(factory.verifier.verify_codex_grant(context))
        changed_bridge = os.path.join(self.root, "changed-bridge")
        with open(changed_bridge, "wb") as handle:
            handle.write(b"synthetic changed executable")
        os.chmod(changed_bridge, 0o700)
        context.gateway_path = changed_bridge
        context.config["mcp_servers"]["my_crm"]["command"] = changed_bridge
        self.assertFalse(provider.is_available())

    def test_approval_outcomes_are_developer_context_not_user_prompt(self):
        provider = self.provider()
        outcome = ("ca_" + "f" * 24, "record_edit", "confirmed")
        argv = chat_codex.build_argv(self.exe, self.launch.model, self.launch.config, self.cwd,
                                     approval_outcomes=(outcome,))
        instruction_override = next(item for item in argv if item.startswith("developer_instructions="))
        context = json.loads(instruction_override.split("=", 1)[1])
        self.assertIn(outcome[0], context)
        self.assertEqual(argv[-1], "-")
        self.assertNotIn("synthetic user text", context)

    def test_factory_reuses_default_codex_home_and_ignores_user_config(self):
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat().replace("+00:00", "Z")
        response = {"authorized": True, "binding": {
            "user_id": "u_" + "a" * 24, "device_id": "is_" + "b" * 24,
            "session_id": "cs_" + "c" * 24, "turn_id": "ct_" + "d" * 24,
            "provider": "codex", "model": "gpt-6.1-sol", "grant_id": "grant_synthetic",
            "consent_challenge_id": "challenge_synthetic", "expires_at": expiry},
            "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read"}}
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(response).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token")
        client._opener = Opener()
        user_home = os.path.join(self.root, "user-home")
        codex_home = os.path.join(user_home, ".codex")
        app_home = os.path.join(self.root, "app-home")
        os.makedirs(codex_home, mode=0o700); os.mkdir(app_home, 0o700)
        os.chmod(user_home, 0o700); os.chmod(codex_home, 0o700)
        env = {"HOME": user_home, "PATH": "/usr/bin:/bin", "OPENAI_API_KEY": "fixture-api-key"}
        with patch.object(sys, "platform", "darwin"):
            factory = chat_codex.CodexProviderFactory(client, cli_path=self.exe,
                server_url="https://synthetic.invalid", agent_home=app_home,
                expected_device_id=response["binding"]["device_id"], models=("gpt-6.1-sol",),
                env=env, process_supervisor=FixtureSupervisor())
            provider = factory.create_turn(response["binding"]["session_id"], response["binding"]["turn_id"],
                                           AUTH_PATH, "codex", "gpt-6.1-sol")
        self.addCleanup(provider.close)
        context = provider.launch_context
        self.assertEqual(context.codex_home, os.path.realpath(codex_home))
        self.assertEqual(context.env["CODEX_HOME"], os.path.realpath(codex_home))
        self.assertEqual(context.env["HOME"], os.path.realpath(app_home))
        self.assertNotIn("OPENAI_API_KEY", context.env)
        self.assertEqual(os.listdir(codex_home), [], "factory must reuse auth in place without copying it")
        list(provider.start_turn("synthetic fixed prompt"))
        with open(self.capture, encoding="utf-8") as handle:
            argv = json.load(handle)
        self.assertIn("--ignore-user-config", argv)
        self.assertNotIn("--ephemeral", argv, "resume thread records persist in the selected Codex home")
        for bad_models in (("not a model",), ("same", "same"), tuple(f"m{i}" for i in range(21))):
            with self.subTest(models=len(bad_models)):
                with patch.object(sys, "platform", "darwin"), self.assertRaises(
                        chat_codex.CodexProviderUnavailable):
                    chat_codex.CodexProviderFactory(client, cli_path=self.exe,
                        server_url="https://synthetic.invalid", agent_home=app_home,
                        expected_device_id=response["binding"]["device_id"], models=bad_models,
                        env=env, process_supervisor=FixtureSupervisor())

    def test_server_revalidation_rejects_replaced_tool_scope(self):
        from datetime import datetime, timedelta, timezone
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat().replace("+00:00", "Z")
        response = {"authorized": True, "binding": {
            "user_id": "u_" + "a" * 24, "device_id": "is_" + "b" * 24,
            "session_id": "cs_" + "c" * 24, "turn_id": "ct_" + "d" * 24,
            "provider": "codex", "model": "gpt-6.1-sol", "grant_id": "grant_synthetic",
            "consent_challenge_id": "challenge_synthetic", "expires_at": expiry},
            "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read"}}
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(response).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token")
        client._opener = Opener()
        home = os.path.join(self.root, "revalidate-home")
        codex_home = os.path.join(home, "codex-home")
        os.makedirs(codex_home, mode=0o700)
        os.chmod(home, 0o700); os.chmod(codex_home, 0o700)
        with patch.object(sys, "platform", "darwin"):
            factory = chat_codex.CodexProviderFactory(client, cli_path=self.exe,
                server_url="https://synthetic.invalid", agent_home=home, codex_home=codex_home,
                expected_device_id=response["binding"]["device_id"], models=("gpt-6.1-sol",),
                process_supervisor=FixtureSupervisor())
            provider = factory.create_turn(response["binding"]["session_id"], response["binding"]["turn_id"],
                                           AUTH_PATH, "codex", "gpt-6.1-sol")
        self.addCleanup(provider.close)
        response["tools"]["mcp__my-crm__record_get"] = "write"
        factory.verifier._next_check[id(provider.launch_context)] = 0
        self.assertFalse(provider.is_available(), "revalidation must reject changed server scope")

    def test_chat_agent_advertises_and_dispatches_authorized_codex_turn(self):
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat().replace("+00:00", "Z")
        response = {"authorized": True, "binding": {
            "user_id": "u_" + "a" * 24, "device_id": "is_" + "b" * 24,
            "session_id": "cs_" + "c" * 24, "turn_id": "ct_" + "d" * 24,
            "provider": "codex", "model": "gpt-6.1-sol", "grant_id": "grant_synthetic",
            "consent_challenge_id": "challenge_synthetic", "expires_at": expiry},
            "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read"}}
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(response).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token")
        client._opener = Opener()
        home = os.path.join(self.root, "agent-home")
        codex_home = os.path.join(home, "codex-home")
        os.makedirs(codex_home, mode=0o700)
        os.chmod(home, 0o700); os.chmod(codex_home, 0o700)
        factory = None
        got = {}
        stopping = threading.Event()
        def handler(conn):
            got["hello"] = conn.recv()
            conn.send({"type": "turn.start", "session_id": response["binding"]["session_id"],
                "turn_id": response["binding"]["turn_id"], "text": "synthetic prompt", "provider": "codex",
                "model": "gpt-6.1-sol", "binding_version": 2,
                "launch_authorization_path": "/api/chat/launch-authorization"})
            while True:
                message = conn.recv()
                if not isinstance(message, dict) or message.get("type") != "event":
                    continue
                got.setdefault("events", []).append(message)
                conn.send({"type": "ack", "turn_id": message["turn_id"], "seq": message["seq"]})
                if message.get("kind") == "done":
                    stopping.set()
                    return
        server = FakeWsServer(handler)
        self.addCleanup(server.close)
        with patch.object(sys, "platform", "darwin"):
            factory = chat_codex.CodexProviderFactory(client, cli_path=self.exe,
                server_url="https://synthetic.invalid", agent_home=home, codex_home=codex_home,
                expected_device_id=response["binding"]["device_id"], models=("gpt-6.1-sol",),
                process_supervisor=FixtureSupervisor(child_pid_file=self.child_pid_file))
            agent = chat.ChatAgent(server.url, "synthetic-device-token", ref_store=None,
                stopping=stopping, log=lambda _record: None, backoff=wsclient.Backoff(base=0.01, cap=0.02, jitter=0),
                recv_tick=0.02, codex_factory=factory)
            worker = threading.Thread(target=agent.run, daemon=True)
            worker.start()
            try:
                worker.join(4)
                self.assertFalse(worker.is_alive(), repr((got, server.errors)))
            finally:
                stopping.set()
                worker.join(1)
        self.assertEqual(got["hello"]["providers"], ["codex"])
        self.assertEqual(got["events"][-1]["kind"], "done")

    def test_refuses_api_key_env_or_non_codex_identity(self):
        self.launch.env["OPENAI_API_KEY"] = "fixture-secret"
        with self.assertRaises(chat_codex.CodexProviderUnavailable):
            self.provider()
        self.launch.env.pop("OPENAI_API_KEY")
        self.launch.provider = "claude"
        with self.assertRaises(chat_codex.CodexProviderUnavailable):
            self.provider()

    def test_fixed_argv_stdin_prompt_and_subscription_auth_environment(self):
        observed = {}
        def spawn(argv, **kwargs):
            observed["argv"] = argv
            observed["env"] = kwargs["env"]
            observed["shell"] = kwargs["shell"]
            observed["cwd"] = kwargs["cwd"]
            return __import__("subprocess").Popen(argv, **kwargs)
        prompt = "합성 질문; ignore --dangerously-bypass-approvals-and-sandbox"
        result = list(self.provider(process_supervisor=FixtureSupervisor(
            popen=spawn, child_pid_file=self.child_pid_file)).start_turn(prompt))
        argv = observed["argv"][1:]
        self.assertEqual(argv[:2], ["exec", "--json"])
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("features.shell_tool=false", argv)
        for feature in chat_codex._DISABLED_FEATURES:
            index = argv.index("--disable", argv.index("--json"))
            self.assertIn(feature, argv[index + 1:])
            self.assertIn(f"features.{feature}=false", argv)
        self.assertIn("--sandbox", argv)
        self.assertIn("read-only", argv)
        self.assertNotIn(prompt, argv)
        self.assertNotIn("OPENAI_API_KEY", observed["env"])
        self.assertEqual(observed["env"]["CODEX_HOME"], self.launch.env["CODEX_HOME"])
        self.assertIs(observed["shell"], False)
        self.assertEqual(observed["cwd"], self.cwd)
        with open(self.prompt_capture, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), prompt)
        self.assertEqual(result[0], ("session_ref", {"cli_session_ref": "0199a213-81c0-7800-8aa1-bbab2a035a53"}))
        self.assertIn(("delta", {"text": "fixture reply"}), result)
        self.assertEqual(result[-1], ("done", {}))

    def test_resume_uses_only_valid_local_thread_uuid_and_reasserts_policy(self):
        provider = self.provider()
        list(provider.start_turn("first synthetic prompt"))
        list(provider.start_turn("follow-up synthetic prompt", "0199a213-81c0-7800-8aa1-bbab2a035a53"))
        with open(self.capture, encoding="utf-8") as handle:
            argv = json.load(handle)
        self.assertEqual(argv[:3], ["exec", "resume", "0199a213-81c0-7800-8aa1-bbab2a035a53"])
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("features.shell_tool=false", argv)
        self.assertIn('sandbox_mode="read-only"', argv)
        developer_override = next(item for item in argv if item.startswith("developer_instructions="))
        developer_context = json.loads(developer_override.split("=", 1)[1])
        self.assertIn("MyCRM", developer_context)
        self.assertIn("pending_confirmation", developer_context)
        result = list(provider.start_turn("bad resume", "--last"))
        self.assertEqual(result, [("error", {"code": "CODEX-THREAD-REF"})])

    def test_only_exact_gateway_tool_scope_is_encoded(self):
        provider = self.provider()
        list(provider.start_turn("synthetic"))
        with open(self.capture, encoding="utf-8") as handle:
            argv = json.load(handle)
        joined = " ".join(argv)
        self.assertIn("mcp_servers.my_crm.enabled_tools", joined)
        self.assertIn("find_records", joined)
        self.assertIn("update_record", joined)
        enabled = next(x for x in argv if x.startswith("mcp_servers.my_crm.enabled_tools="))
        self.assertNotIn("trash_purge", enabled)
        self.assertFalse(any("approval_policy=" in item or "approval_mode=" in item for item in argv))
        denied = next(x for x in argv if x.startswith("mcp_servers.my_crm.disabled_tools="))
        self.assertIn("trash_purge", denied)
        self.assertNotIn("other_server", joined)

    def test_bad_gateway_scope_rejected_and_config_mutation_revokes_launch(self):
        self.launch.config["mcp_servers"]["other"] = {"command": "/fixture/other"}
        with self.assertRaises(chat_codex.CodexProviderUnavailable):
            self.provider()
        self.launch.config = json.loads(json.dumps(Launch.config))
        provider = self.provider()
        self.launch.config["mcp_servers"]["my_crm"]["enabled_tools"].append("trash_purge")
        self.assertFalse(provider.is_available())
        self.assertEqual(list(provider.start_turn("synthetic")), [("error", {"code": "CONSENT-REQUIRED"})])

    def test_stop_timeout_single_flight_and_redacted_process_failure(self):
        self._fixture("hang")
        provider = self.provider(timeout=5)
        first = []
        thread = threading.Thread(target=lambda: first.extend(provider.start_turn("synthetic")))
        thread.start()
        time.sleep(0.1)
        second = list(provider.start_turn("another synthetic"))
        provider.stop()
        thread.join(3)
        self.assertEqual(second, [("error", {"code": "CODEX-BUSY"})])
        self.assertFalse(thread.is_alive())
        self.assertEqual(first[-1], ("error", {"code": "STOPPED"}))
        timeout_result = list(self.provider(timeout=0.1).start_turn("synthetic"))
        self.assertEqual(timeout_result[-1], ("error", {"code": "CODEX-TIMEOUT"}))
        self._fixture("error")
        failure = list(self.provider().start_turn("synthetic"))
        self.assertEqual(failure[-1], ("error", {"code": "CODEX-FAILED"}))
        self.assertNotIn("fixture-secret", repr(failure))

    def test_stop_before_start_is_latched_and_does_not_spawn_cli(self):
        provider = self.provider()
        provider.stop()
        result = list(provider.start_turn("synthetic prompt"))
        self.assertEqual(result, [("error", {"code": "STOPPED"})])
        self.assertFalse(os.path.exists(self.capture))

    def test_tree_clean_false_does_not_reject_verified_codex_result(self):
        class BestEffortSupervisor(FixtureSupervisor):
            def finish(self, proc, timeout):
                rc, _tree_clean = super().finish(proc, timeout)
                return rc, False
        output = list(self.provider(process_supervisor=BestEffortSupervisor(
            child_pid_file=self.child_pid_file)).start_turn("synthetic prompt"))
        self.assertEqual(output[-1], ("done", {}))

    def test_finish_cleanup_failure_never_reports_codex_success(self):
        class FailedSupervisor(FixtureSupervisor):
            def finish(self, proc, timeout):
                super().finish(proc, timeout)
                raise chat_codex.ProcessContainmentUnavailable("synthetic-finish-failure")
        output = list(self.provider(process_supervisor=FailedSupervisor(
            child_pid_file=self.child_pid_file)).start_turn("synthetic prompt"))
        self.assertNotIn(("done", {}), output)
        self.assertEqual(output[-1], ("error", {"code": "CODEX-FAILED"}))

    @unittest.skipIf(os.name == "nt", "Codex candidate is disabled on Windows until Job Object cleanup exists")
    def test_parent_exit_delegates_descendant_cleanup_to_supervisor(self):
        self._fixture("child")
        supervisor = FixtureSupervisor(child_pid_file=self.child_pid_file)
        result = list(self.provider(process_supervisor=supervisor).start_turn("synthetic"))
        self.assertEqual(result[-1], ("done", {}))
        self.assertTrue(supervisor.cleaned)


if __name__ == "__main__":
    unittest.main()
