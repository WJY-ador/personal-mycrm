"""ClaudeProvider contract tests use only a generated fixture executable; no real CLI/model is called."""
from __future__ import annotations

import json
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from agent import chat_claude
from agent.chat_process_supervisor import MacOSProcessSupervisor
from agent.chat_launch_authority import LaunchAuthorization, LaunchAuthorizationClient


INIT = {
    "type": "system", "subtype": "init", "session_id": "fixture-session-01",
    "cwd": "/tmp/empty-chat", "tools": ["mcp__my-crm__find", "mcp__my-crm__write"],
    "mcp_servers": [{"name": "my-crm", "status": "connected"}],
    "model": "claude-sonnet-4-5", "permissionMode": "default", "apiKeySource": "oauth",
}
ASSISTANT = {
    "type": "assistant", "session_id": "fixture-session-01",
    "message": {"role": "assistant", "content": [
        {"type": "text", "text": "확인했습니다."},
        {"type": "tool_use", "id": "tool-1", "name": "mcp__my-crm__find", "input": {"query": "synthetic"}},
    ]},
}
TOOL_RESULT = {
    "type": "user", "session_id": "fixture-session-01",
    "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tool-1", "content": "synthetic result"},
    ]},
}
RESULT = {
    "type": "result", "subtype": "success", "is_error": False,
    "result": "확인했습니다.", "session_id": "fixture-session-01",
}


class Launch:
    user_id = "user-synthetic"
    session_id = "cs_synthetic"
    device_id = "device-synthetic"
    provider = "claude"
    cli_path = ""
    cli_sha256 = ""
    consent_id = "consent-synthetic"
    consent_expires_at = time.time() + 60
    bridge = None
    config = {}
    tools = {"mcp__my-crm__find": "read", "mcp__my-crm__write": "write"}
    env = {"HOME": "/fixture/home", "PATH": "/usr/bin"}
    cwd = "/tmp/empty-chat"

    def current(self):
        return True


class FixtureAuthority:
    """Test-only authenticated authority; production never registers this object."""

    def __init__(self, cli_path, cli_sha256, bridge_path, bridge_sha256):
        self.cli_path = cli_path
        self.cli_sha256 = cli_sha256
        self.bridge_path = bridge_path
        self.bridge_sha256 = bridge_sha256

    def __call__(self, grant):
        bridge = getattr(grant, "bridge", None)
        expected_config = {"mcpServers": {"my-crm": {"command": self.bridge_path, "args": []}}}
        return (
            grant.current() is True
            and grant.user_id == "user-synthetic"
            and grant.device_id == "device-synthetic"
            and grant.session_id == "cs_synthetic"
            and grant.provider == "claude"
            and grant.model == "claude-sonnet-4-5"
            and grant.cli_path == self.cli_path
            and grant.cli_sha256 == self.cli_sha256
            and grant.consent_id == "consent-synthetic"
            and grant.consent_expires_at > time.time()
            and bridge == chat_claude.PinnedBridgeDescriptor(self.bridge_path, (), self.bridge_sha256)
            and grant.config == expected_config
        )


def simulated_macos(test):
    """Exercise platform-independent factory validation without spawning a process."""
    return patch.object(chat_claude, "sys", types.SimpleNamespace(platform="darwin", executable=sys.executable))(test)


class ClaudeProviderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chat-claude-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.capture = os.path.join(self.root, "argv.json")
        self.mcp_capture = os.path.join(self.root, "mcp-config-observed.json")
        self.bridge_pid_file = os.path.join(self.root, "bridge.pid")
        self.input_capture = os.path.join(self.root, "input.jsonl")
        self.runtime = os.path.join(self.root, "runtime")
        self.cwd = os.path.join(self.root, "work")
        os.mkdir(self.runtime, 0o700)
        os.mkdir(self.cwd, 0o700)
        self.exe = os.path.join(self.root, "claude-fixture")
        self.bridge_exe = os.path.join(self.root, "mcp-bridge-fixture")
        self._bridge_fixture()
        self._fixture("outputs")
        self.launch = Launch()
        with open(self.exe, "rb") as f:
            cli_sha256 = hashlib.sha256(f.read()).hexdigest()
        with open(self.bridge_exe, "rb") as f:
            bridge_sha256 = hashlib.sha256(f.read()).hexdigest()
        self.launch.bridge = chat_claude.PinnedBridgeDescriptor(self.bridge_exe, (), bridge_sha256)
        self.launch.cli_path = self.exe
        self.launch.cli_sha256 = cli_sha256
        self.launch.config = {"mcpServers": {"my-crm": {"command": self.bridge_exe, "args": []}}}
        self.launch.tools = {"mcp__my-crm__find": "read", "mcp__my-crm__write": "write"}
        self.launch.cwd = self.cwd
        self.launch.runtime_dir = self.runtime
        self.launch.model = "claude-sonnet-4-5"
        self.launch.env = {"HOME": self.root, "PATH": os.environ.get("PATH", "/usr/bin")}
        self.authority = FixtureAuthority(self.exe, cli_sha256, self.bridge_exe, bridge_sha256)
        self.authority_patch = patch.object(chat_claude, "_TRUSTED_LAUNCH_VERIFIER", self.authority)
        self.authority_patch.start()
        self.addCleanup(self.authority_patch.stop)

    def _bridge_fixture(self):
        script = "#!/usr/bin/env python3\nimport json,sys\n"
        script += "for line in sys.stdin:\n"
        script += "  req=json.loads(line); method=req.get('method')\n"
        script += "  if method == 'initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'synthetic-mcp','version':'1'}}\n"
        script += "  elif method == 'tools/list': result={'tools':[{'name':'find','description':'synthetic'}]}\n"
        script += "  elif method == 'tools/call': result={'content':[{'type':'text','text':'synthetic result'}]}\n"
        script += "  else: continue\n"
        script += "  print(json.dumps({'jsonrpc':'2.0','id':req.get('id'),'result':result}),flush=True)\n"
        with open(self.bridge_exe, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(self.bridge_exe, 0o700)

    def _fixture(self, mode):
        script = "#!/usr/bin/env python3\n" + "import json, os, pathlib, sys, time\n"
        script += f"mode={mode!r}\n"
        script += f"pathlib.Path({self.capture!r}).write_text(json.dumps(sys.argv[1:]))\n"
        script += f"config_path=sys.argv[sys.argv.index('--mcp-config')+1]\n"
        script += "config=json.loads(pathlib.Path(config_path).read_text())\n"
        script += f"pathlib.Path({self.mcp_capture!r}).write_text(json.dumps(config))\n"
        script += "line=sys.stdin.readline()\n"
        script += f"pathlib.Path({self.input_capture!r}).write_text(line)\n"
        script += "if mode == 'hang': time.sleep(30)\n"
        script += "if mode == 'error': sys.stderr.write('ANTHROPIC_API_KEY=fixture-secret\\n'); sys.exit(7)\n"
        script += "if mode == 'echo': print(json.dumps({'type':'assistant','session_id':'fixture-session-01','message':{'role':'assistant','content':[{'type':'text','text':'fixture reply'}]} }), flush=True)\n"
        script += "if mode == 'forbidden-tool':\n"
        script += "  print(json.dumps(" + repr(json.dumps(INIT)) + "), flush=True)\n"
        script += "  print(json.dumps({'type':'assistant','session_id':'fixture-session-01','message':{'role':'assistant','content':[{'type':'tool_use','id':'bad-tool','name':'Bash','input':{'command':'echo forbidden'}}]}}), flush=True)\n"
        script += "if mode == 'outputs':\n"
        script += "  server=config['mcpServers']['my-crm']; child=__import__('subprocess').Popen([server['command'],*server['args']],stdin=__import__('subprocess').PIPE,stdout=__import__('subprocess').PIPE,stderr=__import__('subprocess').DEVNULL,text=True)\n"
        script += "  def request(i,method):\n    child.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':{}})+'\\n'); child.stdin.flush(); return json.loads(child.stdout.readline())\n"
        script += "  init=request(1,'initialize'); listed=request(2,'tools/list')\n"
        script += f"  pathlib.Path({self.bridge_pid_file!r}).write_text(str(child.pid))\n"
        script += f"  pathlib.Path({(self.input_capture + '.mcp')!r}).write_text(json.dumps({{'initialize':init,'tools':listed}}))\n"
        script += "  from json import dumps\n"
        script += "  for item in (" + ",".join(repr(json.dumps(x, ensure_ascii=False)) for x in (INIT, ASSISTANT, TOOL_RESULT, RESULT)) + "):\n"
        script += "    print(item, flush=True)\n"
        with open(self.exe, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(self.exe, 0o700)
        if hasattr(self, "launch"):
            with open(self.exe, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            self.launch.cli_sha256 = digest
            self.authority.cli_sha256 = digest

    def provider(self, **overrides):
        args = dict(cli_path=self.exe, model="claude-sonnet-4-5", launch_context=self.launch,
                    launch_verifier=self.authority, timeout=1.0)
        args.update(overrides)
        return chat_claude.ClaudeProvider(**args)

    def auth_client(self, authorization, later=None):
        def payload(value):
            return {"authorized": True, "binding": {
                "user_id": value.user_id, "device_id": value.device_id, "session_id": value.session_id,
                "turn_id": value.turn_id, "provider": value.provider, "model": value.model,
                "grant_id": value.grant_id, "consent_challenge_id": value.consent_challenge_id,
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value.expires_at))},
                "tools": dict(value.tools)}
        replies = [payload(authorization)]
        if later is not None:
            replies.append(later)
        class Reply:
            status = 200
            def __init__(self, data): self.data = json.dumps(data).encode()
            def read(self, *_args): return self.data
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs):
                if not replies:
                    raise OSError("synthetic transport failure")
                item = replies.pop(0)
                if isinstance(item, BaseException): raise item
                return Reply(item)
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token")
        client._opener = Opener()  # test-only synthetic HTTPS transport; production factory sees default transport construction
        return client

    def test_requires_verified_gateway_and_pc_consent_before_provider_exists(self):
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            chat_claude.ClaudeProvider(cli_path=self.exe, model="claude-sonnet-4-5")
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            self.provider(launch_verifier=lambda _grant: False)

    def test_rejects_modified_pinned_gateway_executable(self):
        with open(self.bridge_exe, "a", encoding="utf-8") as f:
            f.write("# modified after grant\n")
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            self.provider()

    def test_rejects_modified_pinned_cli_executable(self):
        with open(self.exe, "a", encoding="utf-8") as f:
            f.write("# modified after grant\n")
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            self.provider()

    def test_test_verifier_cannot_create_production_launch_authority(self):
        with patch.object(chat_claude, "_TRUSTED_LAUNCH_VERIFIER", None):
            with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
                self.provider(launch_verifier=lambda _grant: True)

    def test_server_factory_rejects_unsupported_platform(self):
        client = self.auth_client(LaunchAuthorization("u", "d", "s", "t", "claude", "model", "g", "c", time.time() + 10, {}))
        with patch.object(chat_claude, "sys", types.SimpleNamespace(platform="linux", executable=sys.executable)):
            with self.assertRaisesRegex(chat_claude.ClaudeProviderUnavailable, "platform"):
                chat_claude.ClaudeProviderFactory(client, cli_path=self.exe, server_url="https://synthetic.invalid",
                    agent_home=self.root, expected_device_id="d", temp_parent=self.root)

    @simulated_macos
    def test_server_factory_binds_launch_context_and_strips_api_key_environment(self):
        authorization = LaunchAuthorization("user-synthetic", "device-synthetic", "cs_synthetic", "ct_synthetic",
            "claude", "claude-sonnet-4-5", "grant-synthetic", "challenge-synthetic",
            time.time() + 10, {"mcp__my-crm__record_get": "read", "mcp__my-crm__record_add": "write"})
        client = self.auth_client(authorization)
        factory = chat_claude.ClaudeProviderFactory(client, cli_path=self.exe, server_url="https://synthetic.invalid",
            agent_home=self.root, env={"HOME": self.root, "PATH": "/usr/bin", "ANTHROPIC_API_KEY": "must-not-inherit"},
            expected_device_id="device-synthetic", temp_parent=self.root)
        provider = factory.create_turn("cs_synthetic", "ct_synthetic", "/api/chat/launch-authorization",
                                       "claude", "claude-sonnet-4-5")
        self.assertEqual(provider.launch_context.user_id, "user-synthetic")
        self.assertEqual(provider.launch_context.device_id, "device-synthetic")
        self.assertEqual(provider.launch_context.turn_id, "ct_synthetic")
        bridge_config = provider.launch_context.config["mcpServers"]["my-crm"]
        self.assertEqual(bridge_config["command"], provider.launch_context.bridge.executable)
        self.assertIn("agent.chat_mcp_bridge", bridge_config["args"])
        self.assertEqual(bridge_config["args"][bridge_config["args"].index("--session-id") + 1], "cs_synthetic")
        self.assertEqual(bridge_config["args"][bridge_config["args"].index("--turn-id") + 1], "ct_synthetic")
        self.assertEqual(bridge_config["args"][bridge_config["args"].index("--device-id") + 1], "device-synthetic")
        self.assertEqual(set(provider.launch_context.tools), {"mcp__my-crm__find", "mcp__my-crm__read", "mcp__my-crm__write"})
        self.assertNotIn("ANTHROPIC_API_KEY", provider.launch_context.env)
        self.assertFalse(os.listdir(provider.launch_context.cwd))
        provider.close()

    @simulated_macos
    def test_server_factory_denies_binding_tamper_before_provider_or_spawn(self):
        bad = LaunchAuthorization("user-synthetic", "device-attacker", "cs_synthetic", "ct_synthetic",
            "claude", "claude-sonnet-4-5", "grant-synthetic", "challenge-synthetic", time.time() + 10,
            {"mcp__my-crm__record_get": "read"})
        factory = chat_claude.ClaudeProviderFactory(self.auth_client(bad), cli_path=self.exe, server_url="https://synthetic.invalid",
            agent_home=self.root, env={"HOME": self.root, "PATH": "/usr/bin"}, expected_device_id="device-synthetic", temp_parent=self.root)
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            factory.create_turn("cs_synthetic", "ct_synthetic", "/api/chat/launch-authorization",
                                "claude", "claude-sonnet-4-5")

    @simulated_macos
    def test_server_factory_rejects_publicly_injected_transport(self):
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token", opener=object())
        self.assertFalse(client.production_transport)
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            chat_claude.ClaudeProviderFactory(client, cli_path=self.exe, server_url="https://synthetic.invalid",
                agent_home=self.root, expected_device_id="device-synthetic", temp_parent=self.root)

    @simulated_macos
    def test_server_factory_uses_internal_sidecar_subcommand_when_frozen(self):
        client = self.auth_client(LaunchAuthorization("user-synthetic", "device-synthetic", "cs_synthetic", "ct_synthetic",
            "claude", "claude-sonnet-4-5", "grant-synthetic", "challenge-synthetic", time.time() + 10,
            {"mcp__my-crm__record_get": "read"}))
        with patch.object(chat_claude.sys, "frozen", True, create=True), patch.object(chat_claude.sys, "executable", self.exe):
            factory = chat_claude.ClaudeProviderFactory(client, cli_path=self.exe, server_url="https://synthetic.invalid",
                agent_home=self.root, expected_device_id="device-synthetic", temp_parent=self.root)
            provider = factory.create_turn("cs_synthetic", "ct_synthetic", "/api/chat/launch-authorization",
                                           "claude", "claude-sonnet-4-5")
            bridge = provider.launch_context.bridge
            self.assertEqual(bridge.executable, os.path.realpath(self.exe))
            self.assertEqual(bridge.args[0], "chat-mcp-bridge")
            self.assertIsNone(bridge.code_path)
            provider.close()

    @simulated_macos
    def test_server_revalidation_failure_rejects_provider_before_child_spawn(self):
        authorization = LaunchAuthorization("user-synthetic", "device-synthetic", "cs_synthetic", "ct_synthetic",
            "claude", "claude-sonnet-4-5", "grant-synthetic", "challenge-synthetic", time.time() + 10,
            {"mcp__my-crm__record_get": "read"})
        client = self.auth_client(authorization, later=OSError("revoked"))
        factory = chat_claude.ClaudeProviderFactory(client, cli_path=self.exe, server_url="https://synthetic.invalid",
            agent_home=self.root, env={"HOME": self.root, "PATH": "/usr/bin"}, expected_device_id="device-synthetic", temp_parent=self.root)
        provider = factory.create_turn("cs_synthetic", "ct_synthetic", "/api/chat/launch-authorization",
                                       "claude", "claude-sonnet-4-5")
        provider.launch_verifier._next_check[id(provider.launch_context)] = 0
        count = []
        original = provider.process_supervisor.spawn
        provider.process_supervisor.spawn = lambda *a, **kw: (count.append(True), original(*a, **kw))[1]
        self.assertEqual(list(provider.start_turn("synthetic")), [("error", {"code": "CONSENT-REQUIRED"})])
        self.assertEqual(count, [])
        provider.close()

    @simulated_macos
    def test_server_revalidation_rejects_replaced_grant_before_child_spawn(self):
        authorization = LaunchAuthorization("user-synthetic", "device-synthetic", "cs_synthetic", "ct_synthetic",
            "claude", "claude-sonnet-4-5", "grant-synthetic", "challenge-synthetic", time.time() + 10,
            {"mcp__my-crm__record_get": "read"})
        replaced = LaunchAuthorization("user-synthetic", "device-synthetic", "cs_synthetic", "ct_synthetic",
            "claude", "claude-sonnet-4-5", "grant-replaced", "challenge-synthetic", time.time() + 10,
            {"mcp__my-crm__record_get": "read"})
        client = self.auth_client(authorization, later=replaced)
        factory = chat_claude.ClaudeProviderFactory(client, cli_path=self.exe, server_url="https://synthetic.invalid",
            agent_home=self.root, env={"HOME": self.root, "PATH": "/usr/bin"}, expected_device_id="device-synthetic", temp_parent=self.root)
        provider = factory.create_turn("cs_synthetic", "ct_synthetic", "/api/chat/launch-authorization",
                                       "claude", "claude-sonnet-4-5")
        provider.launch_verifier._next_check[id(provider.launch_context)] = 0
        spawned = []
        provider.process_supervisor.spawn = lambda *_a, **_kw: spawned.append(True)
        self.assertEqual(list(provider.start_turn("synthetic")), [("error", {"code": "CONSENT-REQUIRED"})])
        self.assertEqual(spawned, [])
        provider.close()

    def test_rejects_arbitrary_mcp_command_even_if_verifier_returns_true(self):
        attacks = (
            {"command": "/tmp/attacker-mcp", "args": []},
            {"command": self.exe, "args": ["--steal"]},
            {"command": self.exe, "args": [], "url": "https://attacker.invalid"},
            {"command": self.exe, "args": [], "env": {"TOKEN": "fixture-secret"}},
        )
        for server in attacks:
            with self.subTest(server=server):
                self.launch.config = {"mcpServers": {"my-crm": server}}
                with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
                    self.provider()

    def test_requires_authenticated_user_device_session_provider_consent_and_expiry_binding(self):
        bindings = (
            ("user_id", "another-user"),
            ("device_id", "another-device"),
            ("session_id", "another-session"),
            ("provider", "codex"),
            ("model", "another-model"),
            ("consent_id", "another-consent"),
            ("consent_expires_at", time.time() - 1),
        )
        for name, value in bindings:
            with self.subTest(binding=name):
                original = getattr(self.launch, name)
                setattr(self.launch, name, value)
                try:
                    with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
                        self.provider()
                finally:
                    setattr(self.launch, name, original)

    def test_supervisor_cleans_same_group_child_before_reaping_leader(self):
        if sys.platform != "darwin":
            self.skipTest("macOS waitid/PGID lifetime behavior")
        child_pid_file = os.path.join(self.root, "descendant.pid")
        code = (
            "import os,time; pid=os.fork(); "
            f"open({child_pid_file!r},'w').write(str(os.getpid())) if pid == 0 else None; "
            "time.sleep(10) if pid == 0 else None"
        )
        supervisor = MacOSProcessSupervisor()
        proc = supervisor.spawn([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            if os.path.exists(child_pid_file):
                info = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if info is not None and info.si_pid == proc.pid:
                    break
            time.sleep(.01)
        else:
            self.fail("fixture leader did not exit with child running")
        with open(child_pid_file, encoding="utf-8") as f:
            child_pid = int(f.read())
        supervisor.terminate_tree(proc)
        state = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(child_pid)],
                               capture_output=True, text=True, check=False).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), f"child still running: {state}")

    def test_refuses_ambient_api_key_environment(self):
        self.launch.env["ANTHROPIC_API_KEY"] = "fixture-secret"
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            self.provider()

    def test_revoked_consent_or_mutated_gateway_config_prevents_launch(self):
        provider = self.provider()
        self.launch.config["mcpServers"]["other"] = {"command": "/fixture/other"}
        self.assertFalse(provider.is_available())
        out = list(provider.start_turn("synthetic prompt"))
        self.assertEqual(out, [("error", {"code": "CONSENT-REQUIRED"})])

        self.launch.config = {"mcpServers": {"my-crm": {"command": self.bridge_exe, "args": []}}}
        provider = self.provider()
        self.launch.current = lambda: False
        self.assertFalse(provider.is_available())

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_argv_uses_fixed_tools_and_never_contains_user_text(self):
        text = "synthetic prompt --dangerously-skip-permissions"
        list(self.provider().start_turn(text))
        with open(self.capture, encoding="utf-8") as f:
            argv = json.load(f)
        self.assertEqual(argv[:3], ["-p", "--input-format", "stream-json"])
        self.assertIn("--restricted", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--disallowedTools", argv)
        denied = set(argv[argv.index("--disallowedTools") + 1:argv.index("--allowedTools")])
        self.assertTrue({"Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch"} <= denied)
        self.assertNotIn("--no-session-persistence", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-4-5")
        allowed_start = argv.index("--allowedTools") + 1
        allowed_end = argv.index("--append-system-prompt") if "--append-system-prompt" in argv else len(argv)
        self.assertEqual(argv[allowed_start:allowed_end], ["mcp__my-crm__find", "mcp__my-crm__write"])
        self.assertNotIn(text, argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        system_context = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn("MyCRM", system_context)
        self.assertIn("pending_confirmation", system_context)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_approval_outcomes_are_appended_as_separate_system_context(self):
        provider = self.provider()
        text = "synthetic original text stays untouched"
        outcome = ("ca_" + "e" * 24, "record_edit", "confirmed")
        list(provider.start_turn(text, approval_outcomes=(outcome,)))
        with open(self.capture, encoding="utf-8") as handle:
            argv = json.load(handle)
        context = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn(outcome[0], context)
        with open(self.input_capture, encoding="utf-8") as handle:
            sent = json.loads(handle.readline())
        self.assertEqual(sent["message"]["content"][0]["text"], text)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_two_turn_session_ref_is_passed_to_cli_resume(self):
        provider = self.provider()
        first = list(provider.start_turn("synthetic first turn"))
        session_ref = next(data["cli_session_ref"] for kind, data in first if kind == "session_ref")
        second = list(provider.start_turn("synthetic second turn", session_ref))
        self.assertEqual(second[-1], ("done", {}))
        with open(self.capture, encoding="utf-8") as f:
            argv = json.load(f)
        self.assertEqual(argv[argv.index("--resume") + 1], session_ref)

    def test_strict_config_runs_only_synthetic_my_crm_bridge_and_group_cleanup_stops_child(self):
        if sys.platform != "darwin":
            self.skipTest("macOS waitid/PGID lifetime behavior")
        out = list(self.provider().start_turn("synthetic MCP turn"))
        self.assertEqual(out[-1], ("done", {}))
        with open(self.mcp_capture, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(set(config), {"mcpServers"})
        self.assertEqual(set(config["mcpServers"]), {"my-crm"})
        server = config["mcpServers"]["my-crm"]
        self.assertEqual(server, {"command": self.bridge_exe, "args": []})
        with open(self.input_capture + ".mcp", encoding="utf-8") as f:
            protocol = json.load(f)
        self.assertEqual([tool["name"] for tool in protocol["tools"]["result"]["tools"]], ["find"])
        with open(self.bridge_pid_file, encoding="utf-8") as f:
            bridge_pid = int(f.read())
        state = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(bridge_pid)],
                               capture_output=True, text=True, check=False).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), f"fake MCP child still running: {state}")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_unexpected_builtin_tool_event_is_rejected_without_dispatch(self):
        self._fixture("forbidden-tool")
        out = list(self.provider().start_turn("synthetic blocked-tool request"))
        self.assertEqual(out[-1], ("error", {"code": "CLI-FAILED"}))

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_stdin_uses_official_user_jsonl_schema_and_env_has_no_api_credentials(self):
        self._fixture("echo")
        captured = {}

        def spawn(argv, **kwargs):
            captured["env"] = kwargs["env"]
            return __import__("subprocess").Popen(argv, **kwargs)

        provider = self.provider(popen=spawn)
        out = list(provider.start_turn("합성 질문"))
        with open(self.capture, encoding="utf-8") as f:
            argv = json.load(f)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertEqual(argv[argv.index("--input-format") + 1], "stream-json")
        self.assertFalse({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"} & captured["env"].keys())
        with open(self.input_capture, encoding="utf-8") as f:
            line = f.read()
        payload = json.loads(line)
        self.assertEqual(payload, {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "합성 질문"}]}})

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_stream_json_maps_known_messages_and_retains_only_local_session_ref(self):
        out = list(self.provider().start_turn("synthetic prompt"))
        self.assertEqual(out[0], ("session_ref", {"cli_session_ref": "fixture-session-01"}))
        self.assertIn(("delta", {"text": "확인했습니다."}), out)
        self.assertIn(("tool_call", {"name": "mcp__my-crm__find", "input": {"query": "synthetic"}}), out)
        self.assertIn(("tool_result", {"name": "mcp__my-crm__find", "ok": True, "summary": "synthetic result"}), out)
        self.assertEqual(out[-1], ("done", {}))

    def test_rejects_purge_and_non_mcp_tools_even_if_launch_claims_them(self):
        bad = Launch()
        bad.tools = {"mcp__my-crm__trash_purge": "purge", "Bash": "write"}
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            self.provider(launch_context=bad)
        # Otherwise-valid launch: only the exact MyCRM `purge` alias (allowed tier) may cause rejection.
        self.launch.tools = {"mcp__my-crm__find": "read", "mcp__my-crm__purge": "decide"}
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            self.provider()
        with self.assertRaises(chat_claude.ClaudeProviderUnavailable):
            chat_claude.build_argv(self.exe, "claude-sonnet-4-5", ("mcp__my-crm__purge",), "/tmp/c.json")

    def test_rejects_session_ref_that_is_not_safe_cli_identifier(self):
        provider = self.provider()
        out = list(provider.start_turn("synthetic prompt", "--dangerously-skip-permissions"))
        self.assertEqual(out[0], ("error", {"code": "CLI-SESSION-REF"}))

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_stop_terminates_running_fixture_process(self):
        self._fixture("hang")
        provider = self.provider(timeout=5)
        output = []
        worker = threading.Thread(target=lambda: output.extend(provider.start_turn("synthetic prompt")))
        worker.start()
        time.sleep(0.1)
        provider.stop()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(output[-1], ("error", {"code": "STOPPED"}))

    def test_stop_before_start_is_latched_and_does_not_spawn_fixture(self):
        self._fixture("hang")
        provider = self.provider(timeout=5)
        provider.stop()
        output = list(provider.start_turn("synthetic prompt"))
        self.assertEqual(output, [("error", {"code": "STOPPED"})])
        self.assertFalse(os.path.exists(self.capture), "a cancelled turn must not spawn its CLI child")

    def test_failed_post_exit_cleanup_never_reports_model_success(self):
        from agent.chat_process_supervisor import ProcessContainmentUnavailable
        class FailingCleanupSupervisor(MacOSProcessSupervisor):
            def spawn(self, argv, **kwargs):
                return subprocess.Popen(argv, **kwargs)
            def finish(self, proc, timeout):
                return proc.wait(timeout=timeout), False
            def terminate_tree(self, proc):
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=2)
                raise ProcessContainmentUnavailable("synthetic-signal-failure")
        self._fixture("outputs")
        provider = self.provider(process_supervisor=FailingCleanupSupervisor())
        output = list(provider.start_turn("synthetic prompt"))
        self.assertNotIn(("done", {}), output)
        self.assertEqual(output[-1], ("error", {"code": "CLI-FAILED"}))

    def test_tree_clean_false_alone_does_not_reject_verified_leader_result(self):
        class BestEffortSupervisor(MacOSProcessSupervisor):
            def spawn(self, argv, **kwargs):
                return subprocess.Popen(argv, **kwargs)
            def finish(self, proc, timeout):
                return proc.wait(timeout=timeout), False
            def terminate_tree(self, proc):
                return None
        self._fixture("outputs")
        try:
            output = list(self.provider(process_supervisor=BestEffortSupervisor()).start_turn("synthetic prompt"))
            self.assertEqual(output[-1], ("done", {}))
        finally:
            if os.path.exists(self.bridge_pid_file):
                with open(self.bridge_pid_file, encoding="utf-8") as handle:
                    child_pid = int(handle.read())
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_timeout_kills_process_and_auth_stderr_is_redacted(self):
        self._fixture("hang")
        timeout_out = list(self.provider(timeout=0.1).start_turn("synthetic prompt"))
        self.assertEqual(timeout_out[-1], ("error", {"code": "CLI-TIMEOUT"}))
        self._fixture("error")
        error_out = list(self.provider().start_turn("synthetic prompt"))
        self.assertEqual(error_out[-1], ("error", {"code": "CLI-FAILED"}))
        self.assertNotIn("fixture-secret", repr(error_out))

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_concurrent_turn_is_rejected(self):
        self._fixture("hang")
        provider = self.provider(timeout=5)
        first = []
        worker = threading.Thread(target=lambda: first.extend(provider.start_turn("synthetic prompt")))
        worker.start()
        time.sleep(0.1)
        second = list(provider.start_turn("other synthetic prompt"))
        provider.stop()
        worker.join(3)
        self.assertEqual(second, [("error", {"code": "CLI-BUSY"})])
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
