"""Synthetic full-path free chat test; requires only a local crm_test* PostgreSQL DB.

The test creates an ephemeral CA/server certificate, HTTPS Uvicorn, fake Claude/Codex
executables, and a real stdio MCP bridge. It never reads server/.env, uses user records,
or calls an external model/network.

앱 하나 1.3(2026-11-13): 새 앱 경로 = agent hello ai_links linked → 서 있는 허용(basis device) → 허용 창, grant, 서명 없이
세션 → launch-authorization → 실제 MCP 다리. 끊기(off) hello = 허용 지움 → 새 대화 CONSENT_REQUIRED.
옛 앱(0.1.5, 0.1.6) consent 경로 호환은 desktop 파일 없이 서버만으로 본다: 파이썬 Ed25519 키로 server/consent_signature.py 의
encode_consent 바이트에 서명해 키 등록, challenge 검증, grant 소비 → basis consent 허용 → launch-authorization binding.
"""
from __future__ import annotations

import httpx
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("Set DATABASE_URL to a local crm_test* database")
parsed = urllib.parse.urlsplit(URL)
if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or not parsed.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("Only a local crm_test* database is allowed")

os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = ""
os.environ["AUTHKIT_ISSUER"] = "https://synthetic-auth.invalid"
os.environ["CRM_PUBLIC_URL"] = "https://127.0.0.1:8800"
os.environ["CRM_SESSION_SECRET"] = "synthetic-freechat-session-secret"
os.environ["CRM_WEBCHAT_ENABLED"] = "1"
os.environ["CRM_CHAT_MCP_ENABLED"] = "1"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import webchat  # noqa: E402
from agent import chat as agent_chat  # noqa: E402
from agent.chat_launch_authority import LaunchAuthorizationClient  # noqa: E402
from agent.chat_claude import ClaudeProviderFactory  # noqa: E402
from agent.chat_codex import CodexProviderFactory  # noqa: E402


EMAIL = "synthetic-freechat-e2e@example.invalid"
CLAUDE_MODEL = "claude-synthetic-e2e"   # agent 의 Claude 모델 이름 규칙(claude-…)에 맞춘다
CODEX_MODEL = "synthetic-codex-e2e"
INSTALLATION = "di_" + "e" * 24
SESSION_REQUEST = "synthetic-e2e-session"
CLI_THREAD_ID = "12345678-1234-1234-1234-123456789abc"


class TlsServer:
    def __init__(self, cert, key):
        import uvicorn
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        config = uvicorn.Config(main.app, host="127.0.0.1", port=self.port, log_level="error",
                                ws="websockets", ssl_certfile=str(cert), ssl_keyfile=str(key))
        self.srv = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.srv.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(300):
            if self.srv.started:
                return self
            time.sleep(.03)
        raise RuntimeError("synthetic HTTPS server did not start")

    def __exit__(self, *_):
        self.srv.should_exit = True
        self.thread.join(10)

    @property
    def base(self):
        return f"https://127.0.0.1:{self.port}"

    @property
    def ws(self):
        return f"wss://127.0.0.1:{self.port}/api/device/chat/ws"


class RefStore:
    def __init__(self):
        self.refs, self.bindings = {}, {}
    def bind_session(self, sid, provider, model):
        binding = (provider, model)
        if sid in self.bindings and self.bindings[sid] != binding:
            return False
        self.bindings[sid] = binding
        return True
    def put(self, handle, sid, provider, model, ref):
        self.refs[(handle, sid, provider, model)] = ref
        return True
    def get(self, handle, sid, provider, model):
        return self.refs.get((handle, sid, provider, model))


def make_certificates(folder):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Freechat Test CA")])
    now = datetime.now(timezone.utc)
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
          .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
          .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
              data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
              encipher_only=None, decipher_only=None), True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    leaf = (x509.CertificateBuilder().subject_name(leaf_name).issuer_name(ca_name).public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(__import__('ipaddress').ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=None, decipher_only=None), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
            .sign(ca_key, hashes.SHA256()))
    ca_path, cert_path, key_path = folder / "test-ca.pem", folder / "server.pem", folder / "server-key.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                  serialization.NoEncryption()))
    key_path.chmod(0o600)
    return ca_path, cert_path, key_path


def fake_bridge_wrapper(path, token_path):
    path.write_text(f'''import sys
sys.path.insert(0, {str(HERE.parent)!r})
from agent import chat_mcp_bridge
class SyntheticKeyStore:
    def get(self, account):
        return open({str(token_path)!r}, encoding="utf-8").read()
raise SystemExit(chat_mcp_bridge.main(argv=sys.argv[1:],
    keystore_factory=lambda _service: SyntheticKeyStore()))
''', encoding="utf-8")
    path.chmod(0o700)


def fake_claude(path, ca_path, diagnostic_path, bridge_wrapper, execution_path, model):
    """Fake CLI runs the exact pinned stdio bridge from the MCP config."""
    body = (r'''#!/usr/bin/env python3
import json, os, subprocess, sys
args=sys.argv[1:]
resume='new'
if '--resume' in args:
 idx=args.index('--resume')
 if idx+1>=len(args) or args[idx+1]!='synthetic-cli-session': raise RuntimeError('resume-binding')
 resume='resume'
stage='config'
try:
 cfg=json.load(open(args[args.index('--mcp-config')+1],encoding='utf-8'))['mcpServers']['my-crm']
 env=dict(os.environ); env['SSL_CERT_FILE']=CA_PATH
 if cfg['args'][:2] != ['-m','agent.chat_mcp_bridge']: raise RuntimeError('bridge-command')
 p=subprocess.Popen([cfg['command'],WRAPPER_PATH,*cfg['args'][2:]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,text=True,env=env)
 def rpc(i,method,params=None):
  p.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params or {}},separators=(',',':'))+'\n'); p.stdin.flush()
  return json.loads(p.stdout.readline())
 stage='initialize'; rpc(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'synthetic-cli','version':'1'}})
 stage='tools-list'; listed=rpc(2,'tools/list')
 if 'result' not in listed: raise RuntimeError('tools-list-denied')
 tools=listed['result']['tools']
 # Claude Code 는 MCP 이름에 mcp__my-crm__ 를 스스로 붙인다 — 다리는 접두어 없는 이름을 준다(agent/chat_mcp_bridge._PROVIDER_TOOL_PREFIX)
 if not any(t['name']=='read' for t in tools): raise RuntimeError('read-tool-missing')
 stage='state-get'; call=rpc(3,'tools/call',{'name':'read','arguments':{'op':'state_get','params':{}}})
 if 'result' not in call or call['result'].get('isError') is not False: raise RuntimeError('state-get-denied')
 with open(EXECUTION_PATH,'a',encoding='utf-8') as log: log.write(resume+':state_get-ok\n')
 p.stdin.close(); p.wait(timeout=10)
 if p.returncode: raise RuntimeError('bridge-exit')
except Exception as exc:
 open(DIAG_PATH,'w').write(stage+':'+type(exc).__name__+':'+str(exc)[:80])
 raise
sid='synthetic-cli-session'
print(json.dumps({'type':'system','subtype':'init','session_id':sid,'model':MODEL,
 'tools':['mcp__my-crm__'+t['name'] for t in tools],'mcp_servers':[{'name':'my-crm','status':'connected'}],
 'permissionMode':'dontAsk'}),flush=True)
print(json.dumps({'type':'assistant','session_id':sid,'message':{'content':[
 {'type':'tool_use','id':'tool-1','name':'mcp__my-crm__read','input':{'op':'state_get','params':{}}} ]}}),flush=True)
print(json.dumps({'type':'user','session_id':sid,'message':{'content':[{'type':'tool_result','tool_use_id':'tool-1','content':'synthetic state loaded'}]}}),flush=True)
print(json.dumps({'type':'assistant','session_id':sid,'message':{'content':[{'type':'text','text':'Synthetic state loaded; turn resumed.'}]}}),flush=True)
print(json.dumps({'type':'result','subtype':'success','session_id':sid,'is_error':False}),flush=True)
'''.replace("CA_PATH", repr(str(ca_path))).replace("DIAG_PATH", repr(str(diagnostic_path)))
       .replace("WRAPPER_PATH", repr(str(bridge_wrapper))).replace("EXECUTION_PATH", repr(str(execution_path)))
       .replace("MODEL", repr(model)))
    path.write_text("#!" + sys.executable + "\n" + body.split("\n", 1)[1], encoding="utf-8")
    path.chmod(0o700)


def fake_codex(path, ca_path, diagnostic_path, bridge_wrapper, execution_path, model):
    """Fake Codex CLI drives the actual grant-bound stdio bridge over HTTPS."""
    body = (r'''#!/usr/bin/env python3
import json, os, subprocess, sys
args=sys.argv[1:]
resume='new'
thread_id=THREAD_ID
if len(args)>1 and args[1]=='resume':
 if len(args)<3 or args[2]!=THREAD_ID: raise RuntimeError('resume-binding')
 resume='resume'
stage='config'
try:
 overrides=[args[i+1] for i,a in enumerate(args[:-1]) if a=='-c']
 command=next(x.split('=',1)[1] for x in overrides if x.startswith('mcp_servers.my_crm.command='))
 gateway_args=next(x.split('=',1)[1] for x in overrides if x.startswith('mcp_servers.my_crm.args='))
 command=json.loads(command); gateway_args=json.loads(gateway_args)
 if gateway_args[:2] != ['-m','agent.chat_mcp_bridge']: raise RuntimeError('bridge-command')
 env=dict(os.environ); env['SSL_CERT_FILE']=CA_PATH
 p=subprocess.Popen([command,WRAPPER_PATH,*gateway_args[2:]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,text=True,env=env)
 def rpc(i,method,params=None):
  p.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params or {}},separators=(',',':'))+'\n'); p.stdin.flush()
  return json.loads(p.stdout.readline())
 stage='initialize'; rpc(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'synthetic-codex','version':'1'}})
 stage='tools-list'; listed=rpc(2,'tools/list')
 if 'result' not in listed: raise RuntimeError('tools-list-denied')
 tools=listed['result']['tools']
 if not any(t['name']=='mcp__my-crm__read' for t in tools): raise RuntimeError('read-tool-missing')
 stage='state-get'; call=rpc(3,'tools/call',{'name':'mcp__my-crm__read','arguments':{'op':'state_get','params':{}}})
 if 'result' not in call or call['result'].get('isError') is not False: raise RuntimeError('state-get-denied')
 with open(EXECUTION_PATH,'a',encoding='utf-8') as log: log.write(resume+':state_get-ok\n')
 p.stdin.close(); p.wait(timeout=10)
 if p.returncode: raise RuntimeError('bridge-exit')
except Exception as exc:
 open(DIAG_PATH,'w').write(stage+':'+type(exc).__name__+':'+str(exc)[:80])
 raise
print(json.dumps({'type':'thread.started','thread_id':thread_id}),flush=True)
print(json.dumps({'type':'turn.started','thread_id':thread_id}),flush=True)
print(json.dumps({'type':'item.completed','thread_id':thread_id,'item':{'type':'agent_message','text':'Synthetic state loaded; turn resumed.'}}),flush=True)
print(json.dumps({'type':'turn.completed','thread_id':thread_id}),flush=True)
'''.replace("CA_PATH", repr(str(ca_path))).replace("DIAG_PATH", repr(str(diagnostic_path)))
       .replace("WRAPPER_PATH", repr(str(bridge_wrapper))).replace("EXECUTION_PATH", repr(str(execution_path)))
       .replace("THREAD_ID", repr(CLI_THREAD_ID)))
    path.write_text("#!" + sys.executable + "\n" + body.split("\n", 1)[1], encoding="utf-8")
    path.chmod(0o700)


def old_app_consent(uid, did, bearer, provider, model, request_id):
    """옛 앱 consent 경로(서버만) — 키 begin, activate(PoP 서명) → grant 요청 → challenge → 서명 검증 → 세션이 grant 를 소비해 허용(basis consent)."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import consent_signature

    key = Ed25519PrivateKey.generate()
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    sign = lambda claims: base64.urlsafe_b64encode(key.sign(consent_signature.encode_consent(claims))).rstrip(b"=").decode("ascii")  # noqa: E731
    with db.tx() as c:
        c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'synthetic','darwin',%s) "
                  "ON CONFLICT DO NOTHING", (uid, INSTALLATION, did))
    webchat.grant_request(uid, did, provider, model, request_id)
    begun = webchat.consent_key_begin(uid, bearer, INSTALLATION, der)
    webchat.consent_key_activate(uid, bearer, INSTALLATION, begun["key_id"], sign(begun["claims"]))
    claims = webchat.consent_challenge_issue(uid, bearer, INSTALLATION, request_id)["claims"]
    assert webchat.consent_challenge_verify(uid, bearer, INSTALLATION, claims["nonce"], sign(claims))["state"] == "verified"


class FreechatSyntheticE2ETests(unittest.TestCase):
    def test_ai_link_claude_mcp_response_resume_and_disconnect(self):
        self._run_isolated_provider("claude")

    def test_ai_link_codex_mcp_response_resume_and_disconnect(self):
        self._run_isolated_provider("codex")

    def test_old_app_consent_path_server_only(self):
        self._run_isolated_provider("consent")

    def _run_isolated_provider(self, provider_name):
        """Run each provider in its own app lifespan and readiness-patched process."""
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--run-provider", provider_name],
            cwd=str(HERE.parent), env=env, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0,
            f"isolated synthetic {provider_name} E2E failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    def _run_consent(self):
        """옛 앱 consent 경로 호환(서버만): 서명 검증된 grant 를 세션이 소비 → basis consent 허용 → launch-authorization binding = grant, challenge id."""
        import secrets
        uid = db.user_by_email(EMAIL)["id"]
        try:
            device = imports.device_connect(uid, "synthetic old desktop")
            bearer, did = "Bearer " + device["token"], device["device"]["id"]
            old_app_consent(uid, did, bearer, "claude", CLAUDE_MODEL, SESSION_REQUEST)
            session, _, _ = webchat.session_new(uid, did, "claude", CLAUDE_MODEL, SESSION_REQUEST, capability_ok=True)
            with db.tx() as c:
                permit = c.execute("SELECT basis, grant_id, challenge_id FROM chat_provider_permits WHERE user_id=%s AND device_id=%s",
                                   (uid, did)).fetchone()
                tid = "ct_" + secrets.token_hex(12)
                c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,'synthetic-consent')", (tid, session["session_id"]))
            self.assertEqual(permit["basis"], "consent")
            with patch("webchat.PROVIDER_LAUNCH_READY", True):
                out = webchat._chat_launch_authorization(imports.authenticate(bearer), bearer, session["session_id"], tid)
            self.assertEqual((out["binding"]["grant_id"], out["binding"]["consent_challenge_id"]), (permit["grant_id"], permit["challenge_id"]))
            # 옛 앱이 붙은 장치에 새 앱이 ai_links 없이(옛 hello) 다시 붙어도 consent 허용은 그대로(device 근거만 지운다)
            self.assertEqual(webchat.ai_links_apply({"user_id": uid, "id": did}, None), [])
            with db.tx() as c:
                self.assertEqual(c.execute("SELECT basis FROM chat_provider_permits WHERE user_id=%s AND device_id=%s", (uid, did)).fetchone()["basis"],
                                 "consent")
        finally:
            with db.tx() as c:
                c.execute("DELETE FROM admin_audit WHERE actor_id=%s OR target_id=%s", (uid, uid))
            db.user_delete(uid)

    def _run_provider(self, provider_name):
        model = CLAUDE_MODEL if provider_name == "claude" else CODEX_MODEL
        with tempfile.TemporaryDirectory(prefix="freechat-e2e-") as raw:
            temp = Path(raw)
            ca, cert, key = make_certificates(temp)
            fake_cli = temp / f"fake-{provider_name}"
            cli_diag = temp / "fake-cli-diagnostic.txt"
            cli_executions = temp / "fake-cli-executions.txt"
            bridge_wrapper = temp / "synthetic-bridge-main.py"
            token_path = temp / "synthetic-device-token.txt"
            fake_bridge_wrapper(bridge_wrapper, token_path)
            previous_ca = os.environ.get("SSL_CERT_FILE")
            os.environ["SSL_CERT_FILE"] = str(ca)
            uid = db.user_by_email(EMAIL)["id"]
            device = imports.device_connect(uid, "synthetic desktop")
            token, did = device["token"], device["device"]["id"]
            token_path.write_text(token, encoding="utf-8")
            token_path.chmod(0o600)
            agent_home = temp / "agent-home"
            agent_home.mkdir(mode=0o700)
            agent_home.chmod(0o700)
            codex_home = temp / "codex-home"
            if provider_name == "codex":
                codex_home.mkdir(mode=0o700)
                codex_home.chmod(0o700)
            from agent import config as agent_config
            cfg = agent_config.default_config()
            cfg.update({"server_url": "https://127.0.0.1:443", "source_instance_id": did,
                        "keychain_service": "synthetic-freechat-e2e"})
            agent_config.save(agent_config.Paths(str(agent_home)), cfg)
            stop = threading.Event()
            agent = None
            try:
                with patch("webchat.PROVIDER_LAUNCH_READY", True), patch("chat_mcp_gateway.ATOMIC_DISPATCH_READY", True):
                    with TlsServer(cert, key) as srv:
                        server_url = srv.base
                        cfg["server_url"] = server_url
                        agent_config.save(agent_config.Paths(str(agent_home)), cfg)
                        if provider_name == "claude":
                            fake_claude(fake_cli, ca, cli_diag, bridge_wrapper, cli_executions, model)
                        else:
                            fake_codex(fake_cli, ca, cli_diag, bridge_wrapper, cli_executions, model)
                        try:
                            raw_sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
                            tls_sock = ssl.create_default_context(cafile=str(ca)).wrap_socket(raw_sock, server_hostname="127.0.0.1")
                            tls_sock.close()
                        except Exception as exc:
                            self.fail(f"synthetic TLS failed: {type(exc).__name__}: {exc}")
                        try:
                            probe = agent_chat.wsclient.connect(srv.ws, {"Authorization": "Bearer " + token},
                                ssl_context=ssl.create_default_context(cafile=str(ca)))
                            probe.close()
                        except agent_chat.wsclient.WsError as exc:
                            self.fail(f"direct synthetic WSS handshake failed: kind={exc.kind}, status={exc.status}, code={exc.code}")
                        auth_client = LaunchAuthorizationClient(server_url, lambda: token)
                        if provider_name == "claude":
                            factory = ClaudeProviderFactory(auth_client, cli_path=str(fake_cli), server_url=server_url,
                                agent_home=str(agent_home), expected_device_id=did, models=(model,), timeout=20)
                            factory_kw = {"claude_factory": factory}
                        else:
                            factory = CodexProviderFactory(auth_client, cli_path=str(fake_cli), server_url=server_url,
                                agent_home=str(agent_home), codex_home=str(codex_home), expected_device_id=did,
                                models=(model,), timeout=20)
                            factory_kw = {"codex_factory": factory}
                        process_failures = []
                        if provider_name == "codex":
                            original_spawn = factory.process_supervisor.spawn
                            def observe_codex_spawn(argv, **kwargs):
                                try:
                                    return original_spawn(argv, **kwargs)
                                except Exception as exc:
                                    process_failures.append(f"{type(exc).__name__}:{exc}")
                                    raise
                            factory.process_supervisor.spawn = observe_codex_spawn
                        ref_store = RefStore()
                        links = {provider_name: "linked"}   # 앱이 확인한 CLI 로그인(가짜). 끊기는 아래에서 off 로 바꾼다
                        agent_log = []
                        received = []
                        agent = agent_chat.ChatAgent(srv.ws, token, ref_store=ref_store,
                            agent_version="synthetic", stopping=stop, ai_status=links, ai_check=lambda p: links.get(p, "missing"),
                            backoff=agent_chat.wsclient.Backoff(base=.1, cap=.3, jitter=0), recv_tick=.05, coalesce=0,
                            log=agent_log.append,
                            connect=lambda url, headers: agent_chat.wsclient.connect(
                                url, headers, ssl_context=ssl.create_default_context(cafile=str(ca))), **factory_kw)
                        original_on = agent._on
                        def observed_on(message):
                            received.append((message.get("type"), message.get("request_id")))
                            original_on(message)
                        agent._on = observed_on
                        worker = threading.Thread(target=agent.run, daemon=True)
                        worker.start()
                        with httpx.Client(base_url=server_url, verify=str(ca), timeout=10,
                                          headers={"origin": os.environ["CRM_PUBLIC_URL"]},
                                          cookies={"crm_session": main.site.session_value(uid)}) as h:
                            for _ in range(100):
                                if agent.connects and webchat.hub.connected(uid, did): break
                                time.sleep(.05)
                            self.assertTrue(webchat.hub.connected(uid, did), f"agent WebSocket did not connect: {agent_log}")
                            def permit_rows():
                                with db.tx() as c:
                                    return c.execute("SELECT basis FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider=%s",
                                                     (uid, did, provider_name)).fetchall()
                            for _ in range(100):
                                if permit_rows(): break
                                time.sleep(.05)
                            self.assertEqual([r["basis"] for r in permit_rows()], ["device"],
                                f"hello ai_links linked 가 허용을 세우지 않음: logs={agent_log}, received={received}")
                            session = h.post("/api/chat/sessions", json={"operation":"new", "device_id":did,
                                "provider":provider_name, "model":model, "client_session_id":SESSION_REQUEST})
                            self.assertEqual(session.status_code, 201, session.text)
                            sid = session.json()["session_id"]
                            with db.tx() as c:
                                grants = c.execute("SELECT count(*) AS n FROM chat_provider_grants WHERE user_id=%s", (uid,)).fetchone()["n"]
                                challenges = c.execute("SELECT count(*) AS n FROM chat_consent_challenges WHERE user_id=%s", (uid,)).fetchone()["n"]
                            self.assertEqual((grants, challenges), (0, 0), "새 앱 경로는 grant, 서명이 없다")
                            results = []
                            for number in (1, 2):
                                turn = h.post(f"/api/chat/sessions/{sid}/turns", json={"text":f"synthetic prompt {number}",
                                    "client_turn_id":f"synthetic-turn-{number}"})
                                self.assertEqual(turn.status_code, 201, turn.text)
                                tid = turn.json()["turn_id"]
                                for _ in range(300):
                                    with db.tx() as c:
                                        row = c.execute("SELECT status FROM chat_turns WHERE id=%s", (tid,)).fetchone()
                                    if row["status"] != "running": break
                                    time.sleep(.05)
                                with db.tx() as c:
                                    err = c.execute("SELECT data FROM chat_events WHERE turn_id=%s AND kind='error' ORDER BY seq DESC LIMIT 1", (tid,)).fetchone()
                                self.assertEqual(row["status"], "done",
                                    f"turn {number} failed, event={err['data'] if err else None}, "
                                    f"fake_cli={cli_diag.read_text() if cli_diag.exists() else None}, "
                                    f"process_failures={process_failures}, agent_log={agent_log}")
                                messages = h.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
                                results.append([m["body"] for m in messages if m["turn_id"] == tid and m["role"] == "assistant"])
                            self.assertEqual(results, [["Synthetic state loaded; turn resumed."]] * 2)
                            self.assertEqual(cli_executions.read_text(encoding="utf-8").splitlines(),
                                             ["new:state_get-ok", "resume:state_get-ok"])
                            # 서 있는 허용: 같은 공급자의 새 대화는 다시 묻지 않는다(재시작, 잠금도 허용을 지우지 않는다 — 앱이 CLI 로그인을 보관)
                            again = h.post("/api/chat/sessions", json={"operation": "new", "device_id": did, "provider": provider_name,
                                "model": model, "client_session_id": SESSION_REQUEST + "-again"})
                            self.assertEqual(again.status_code, 201, again.text)
                            # 끊기: 앱 AI 패널 [연결 끊기] = hello ai_links off → 허용 지움 → 새 대화 CONSENT_REQUIRED
                            links[provider_name] = "off"
                            agent.ai_status = dict(links)
                            agent._resend_hello()
                            for _ in range(100):
                                if not permit_rows(): break
                                time.sleep(.05)
                            self.assertEqual(permit_rows(), [])
                            denied = h.post("/api/chat/sessions", json={"operation": "new", "device_id": did, "provider": provider_name,
                                "model": model, "client_session_id": SESSION_REQUEST + "-off"})
                            self.assertEqual((denied.status_code, denied.json().get("code")), (409, "CONSENT_REQUIRED"), denied.text)
            finally:
                stop.set()
                if agent:
                    for th in list(agent.threads): th.join(2)
                with db.tx() as c:
                    c.execute("DELETE FROM admin_audit WHERE actor_id=%s OR target_id=%s", (uid, uid))
                db.user_delete(uid)
                db.close()
                if previous_ca is None: os.environ.pop("SSL_CERT_FILE", None)
                else: os.environ["SSL_CERT_FILE"] = previous_ca


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--run-provider" and sys.argv[2] in ("claude", "codex", "consent"):
        db.init_schema()
        try:
            t = FreechatSyntheticE2ETests()
            t._run_consent() if sys.argv[2] == "consent" else t._run_provider(sys.argv[2])
        finally:
            db.close()
    else:
        db.init_schema()
        unittest.main()
