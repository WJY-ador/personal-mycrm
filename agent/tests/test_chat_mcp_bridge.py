import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

from agent.chat_launch_authority import LaunchAuthorization, LaunchAuthorizationClient
from agent.chat_mcp_bridge import McpStdioBridge


class FakeLaunchClient:
    def __init__(self):
        self.calls = []
        self.scope = LaunchAuthorization(
            user_id="u-synthetic", device_id="d-synthetic", session_id="cs_synthetic",
            turn_id="ct_synthetic", provider="claude", model="claude-synthetic",
            grant_id="grant-synthetic", consent_challenge_id="challenge-synthetic",
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=10)).timestamp(),
            tools=MappingProxyType({"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read", "mcp__my-crm__record_add": "write",
                                    "mcp__my-crm__candidate_decide": "decide"}),
        )

    def authorize(self, path, session_id, turn_id, provider, model):
        self.calls.append(("authorize", session_id, turn_id))
        if (session_id, turn_id, provider, model) != ("cs_synthetic", "ct_synthetic", "claude", "claude-synthetic"):
            raise RuntimeError("denied")
        return self.scope

    def call_mcp(self, authorization, tool, params, *, op=None, bind=""):
        self.calls.append(("call", authorization.session_id, authorization.turn_id, tool, op, params, bind))
        return {"result": {"synthetic": True}}


class McpStdioBridgeTest(unittest.TestCase):
    def test_agent_cli_has_internal_frozen_bridge_subcommand_and_no_token_argument(self):
        from agent import cli
        args = cli._parser().parse_args(["chat-mcp-bridge", "--agent-home", "/synthetic/home",
            "--session-id", "cs_synthetic", "--turn-id", "ct_synthetic", "--device-id", "is_" + "a" * 24,
            "--provider", "claude", "--model", "claude-synthetic",
            "--authorization-path", "/api/chat/launch-authorization"])
        self.assertEqual(args.cmd, "chat-mcp-bridge")
        self.assertFalse(hasattr(args, "token"))

    def test_agent_cli_dispatches_bridge_subcommand_to_loaded_module(self):
        from agent import cli
        with tempfile.TemporaryDirectory(prefix="chat-bridge-cli-global-") as global_home, \
             tempfile.TemporaryDirectory(prefix="chat-bridge-cli-agent-") as agent_home:
            out = io.StringIO()
            argv = ["--home", global_home, "chat-mcp-bridge", "--agent-home", agent_home,
                    "--session-id", "cs_synthetic", "--turn-id", "ct_synthetic", "--device-id", "is_" + "a" * 24,
                    "--provider", "claude", "--model", "claude-synthetic",
                    "--authorization-path", "/api/chat/launch-authorization"]
            with patch.object(cli.chat_mcp_bridge, "main", return_value=0) as bridge_main:
                self.assertEqual(cli.main(argv, out=out), 0)
        bridge_main.assert_called_once()
        self.assertEqual(bridge_main.call_args.kwargs["home"], agent_home)
        self.assertEqual(bridge_main.call_args.args[0][1], agent_home)
        self.assertNotIn("token", repr(bridge_main.call_args))

    def setUp(self):
        self.client = FakeLaunchClient()
        self.bridge = McpStdioBridge(self.client, "/api/chat/launch-authorization", "cs_synthetic",
                                     "ct_synthetic", "claude", "claude-synthetic", "d-synthetic")

    def message(self, method, params=None, msg_id=1):
        raw = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        return json.loads(self.bridge.handle_line(raw))

    def test_tools_list_uses_authorized_ops_and_surface_schema(self):
        # Claude Code adds mcp__my-crm__ itself; the bridge must list bare names for it.
        response = self.message("tools/list")
        self.assertEqual(response["id"], 1)
        tools = response["result"]["tools"]
        self.assertEqual([x["name"] for x in tools], ["find", "read", "write", "decide"])
        by_tool = {x["name"]: x for x in tools}
        self.assertEqual(by_tool["find"]["annotations"], {"readOnlyHint": True})
        self.assertEqual(by_tool["read"]["annotations"], {"readOnlyHint": True})
        self.assertNotIn("annotations", by_tool["write"])
        self.assertNotIn("annotations", by_tool["decide"])
        # F5: a write waits for the person's card; pending is not done; chained writes use created ids next turn.
        for phrase in ("카드로 확인한 뒤 실행", "pending_confirmation은 완료가 아니다", "다음 턴에 created id"):
            self.assertIn(phrase, by_tool["write"]["description"])
        self.assertNotIn("bind", by_tool["write"]["inputSchema"]["properties"])
        by_name = {x["name"]: x["inputSchema"] for x in tools}
        self.assertEqual(by_name["read"]["properties"]["op"]["enum"], ["record_get"])
        self.assertEqual(by_name["write"]["properties"]["op"]["enum"], ["record_add"])
        self.assertEqual(by_name["decide"]["properties"]["op"]["enum"], ["candidate_decide"])
        self.assertNotIn("purge", [x["name"] for x in tools])
        self.assertEqual(self.client.calls, [("authorize", "cs_synthetic", "ct_synthetic")])

    def test_tool_call_forwards_bound_locator_and_rejects_model_identity_fields(self):
        result = self.message("tools/call", {"name": "read",
                                              "arguments": {"op": "record_get", "params": {"record_id": "r_synthetic"}}})
        self.assertEqual(result["result"]["content"][0]["text"], '{"result":{"synthetic":true}}')
        self.assertEqual(self.client.calls[-1], ("call", "cs_synthetic", "ct_synthetic", "read", "record_get",
                                                  {"record_id": "r_synthetic"}, ""))
        denied = self.message("tools/call", {"name": "read",
                                              "arguments": {"session_id": "cs_attacker", "params": {}}}, 2)
        self.assertIn("error", denied)
        self.assertEqual(sum(c[0] == "call" for c in self.client.calls), 1)

    def test_denied_or_unknown_ops_never_reach_http_dispatch(self):
        response = self.message("tools/call", {"name": "decide", "arguments": {"op": "trash_purge", "params": {}}})
        self.assertIn("error", response)
        self.assertFalse(any(c[0] == "call" for c in self.client.calls))

    def test_bridge_revalidation_rejects_changed_user_binding(self):
        self.assertIn("result", self.message("tools/list"))
        old = self.client.scope
        self.client.scope = LaunchAuthorization("u-attacker", old.device_id, old.session_id, old.turn_id,
            old.provider, old.model, old.grant_id, old.consent_challenge_id, old.expires_at, old.tools)
        self.assertIn("error", self.message("tools/list", msg_id=2))

    def test_json_rpc_initialize_and_notifications(self):
        initialized = self.message("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(initialized["result"]["capabilities"], {"tools": {}})
        self.assertIsNone(self.bridge.handle_line('{"jsonrpc":"2.0","method":"notifications/initialized"}'))

    def test_line_limit_and_malformed_json_fail_closed(self):
        self.assertIsNone(self.bridge.handle_line("x" * (256 * 1024 + 1)))
        self.assertIsNone(self.bridge.handle_line("{"))

    def test_tool_call_accepts_cli_meta_without_forwarding_it(self):
        # Shape seen from the real CLI 2.1.322 (probe 2026-11-10).
        result = self.message("tools/call", {"name": "read", "arguments": {"op": "record_get", "params": {}},
                                              "_meta": {"claudecode/toolUseId": "toolu_synthetic", "progressToken": 2}})
        self.assertIn("result", result)
        self.assertEqual(self.client.calls[-1], ("call", "cs_synthetic", "ct_synthetic", "read", "record_get", {}, ""))
        self.assertNotIn("toolu_synthetic", repr(self.client.calls))
        for bad in ({"name": "read", "arguments": {"op": "record_get"}, "_meta": "x"},
                    {"name": "read", "arguments": {"op": "record_get"}, "extra": {}},
                    {"name": "read", "_meta": {}}):
            with self.subTest(params=bad):
                self.assertIn("error", self.message("tools/call", bad, 9))
        self.assertEqual(sum(c[0] == "call" for c in self.client.calls), 1)

    def test_claude_rejects_prefixed_names_and_codex_keeps_them(self):
        prefixed = self.message("tools/call", {"name": "mcp__my-crm__read",
                                                "arguments": {"op": "record_get", "params": {}}})
        self.assertEqual(prefixed["error"]["message"], "MyCRM tool call denied")
        self.assertFalse(any(c[0] == "call" for c in self.client.calls))

        class CodexClient(FakeLaunchClient):
            def authorize(self, path, session_id, turn_id, provider, model):
                self.calls.append(("authorize", session_id, turn_id))
                if provider != "codex":
                    raise RuntimeError("denied")
                return self.scope
        client = CodexClient()
        bridge = McpStdioBridge(client, "/api/chat/launch-authorization", "cs_synthetic",
                                "ct_synthetic", "codex", "claude-synthetic", "d-synthetic")
        listed = json.loads(bridge.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})))
        self.assertEqual([x["name"] for x in listed["result"]["tools"]],
                         ["mcp__my-crm__find", "mcp__my-crm__read", "mcp__my-crm__write", "mcp__my-crm__decide"])
        bare = json.loads(bridge.handle_line(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "read", "arguments": {"op": "record_get", "params": {}}}})))
        self.assertIn("error", bare)
        ok = json.loads(bridge.handle_line(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "mcp__my-crm__read", "arguments": {"op": "record_get", "params": {}}}})))
        self.assertIn("result", ok)

    def test_unknown_request_gets_method_not_found_at_once(self):
        # Claude Code 2.1.322 sends server/discover before initialize and waits ~3 s for a reply.
        response = self.message("server/discover", {}, msg_id=0)
        self.assertEqual(response, {"jsonrpc": "2.0", "id": 0,
                                    "error": {"code": -32601, "message": "Method not found"}})
        self.assertIsNone(self.bridge.handle_line('{"jsonrpc":"2.0","method":"server/discover"}'))
        self.assertIsNone(self.bridge.handle_line('{"jsonrpc":"2.0","id":{"x":1},"method":"server/discover"}'))
        self.assertEqual(self.client.calls, [])

    def test_family_surface_schema_is_pinned_to_server_catalog(self):
        catalog = json.loads((Path(__file__).resolve().parents[2] / "server" / "mcp_catalog.json").read_text())
        self.assertEqual(tuple(f["key"] for f in catalog["families"]), __import__("agent.chat_mcp_bridge", fromlist=["FAMILIES"]).FAMILIES)
        schema = {tool["name"]: tool["inputSchema"] for tool in __import__("agent.chat_mcp_bridge", fromlist=["surface_schemas"]).surface_schemas(
            {"mcp__my-crm__find": "read", "mcp__my-crm__question_list": "read"})}
        self.assertEqual(schema["mcp__my-crm__find"]["properties"]["family"]["enum"], ["", *[f["key"] for f in catalog["families"]]])

    def test_stdio_entrypoint_reads_synthetic_keystore_and_keeps_token_out_of_argv_and_output(self):
        from agent import config
        now = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        auth_reply = {"authorized": True, "binding": {
            "user_id": "u-synthetic", "device_id": "is_" + "a" * 24, "session_id": "cs_synthetic",
            "turn_id": "ct_synthetic", "provider": "claude", "model": "claude-synthetic",
            "grant_id": "grant-synthetic", "consent_challenge_id": "challenge-synthetic", "expires_at": now},
            "tools": {"mcp__my-crm__record_get": "read"}}
        replies = iter((auth_reply, {"result": {"record": "synthetic"}}))
        class Reply:
            status = 200
            def __init__(self, data): self.data = json.dumps(data).encode()
            def read(self, *_args): return self.data
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def __init__(self): self.requests = []
            def open(self, req, timeout): self.requests.append(req); return Reply(next(replies))
        class SyntheticKeyStore:
            def __init__(self, service): self.service = service
            def get(self, account):
                self.account = account
                return "synthetic-device-token"
        with tempfile.TemporaryDirectory(prefix="chat-mcp-bridge-") as home:
            paths = config.Paths(home)
            cfg = config.default_config()
            cfg.update(server_url="https://synthetic.invalid", source_instance_id="is_" + "a" * 24)
            config.save(paths, cfg)
            opener = Opener()
            stdout = io.StringIO()
            argv = ["--agent-home", home, "--session-id", "cs_synthetic", "--turn-id", "ct_synthetic",
                    "--device-id", "is_" + "a" * 24, "--provider", "claude",
                    "--model", "claude-synthetic", "--authorization-path", "/api/chat/launch-authorization"]
            input_data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "read", "arguments": {"op": "record_get", "params": {"record_id": "r_fake"}}}}) + "\n"
            from agent.chat_mcp_bridge import main
            self.assertEqual(main(argv, home=home, keystore_factory=lambda _service: SyntheticKeyStore(_service),
                                  opener=opener, stdin=io.StringIO(input_data), stdout=stdout), 0)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer synthetic-device-token")
        sent = json.loads(opener.requests[1].data)
        self.assertEqual(sent["session_id"], "cs_synthetic")
        self.assertEqual(sent["turn_id"], "ct_synthetic")
        self.assertNotIn("synthetic-device-token", repr(argv) + stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue()) ["result"]["content"][0]["text"], '{"record":"synthetic"}')

    def test_closed_turn_is_denied_even_if_a_new_session_exists_after_launch_check(self):
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        launch = {"authorized": True, "binding": {
            "user_id": "u-synthetic", "device_id": "d-synthetic", "session_id": "cs_old",
            "turn_id": "ct_old", "provider": "claude", "model": "claude-synthetic",
            "grant_id": "g_old", "consent_challenge_id": "ch_old", "expires_at": expiry},
            "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read"}}
        class Reply:
            def __init__(self, status, data): self.status, self.data = status, data
            def read(self, *_args): return self.data
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            requests = []
            def open(self, req, timeout):
                self.requests.append(req)
                if req.full_url.endswith("/api/chat/launch-authorization"):
                    return Reply(200, json.dumps(launch).encode())
                # Synthetic server closed old turn and created a new active session before MCP dispatch.
                return Reply(409, b'{"error":"CONSENT-REQUIRED"}')
        opener = Opener()
        client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-token", opener=opener)
        bridge = McpStdioBridge(client, "/api/chat/launch-authorization", "cs_old", "ct_old",
                                "claude", "claude-synthetic", "d-synthetic")
        response = json.loads(bridge.handle_line(json.dumps({"jsonrpc": "2.0", "id": 7,
            "method": "tools/call", "params": {"name": "read",
            "arguments": {"op": "record_get", "params": {"record_id": "r_fake"}}}})))
        self.assertEqual(response["error"]["message"], "MyCRM tool call denied")
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(json.loads(opener.requests[1].data)["session_id"], "cs_old")
        self.assertEqual(json.loads(opener.requests[1].data)["turn_id"], "ct_old")
        self.assertNotIn("cs_new", opener.requests[1].data.decode())


if __name__ == "__main__":
    unittest.main()
