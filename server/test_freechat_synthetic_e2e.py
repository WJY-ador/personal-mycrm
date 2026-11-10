"""Synthetic full-path free chat test; requires only a local crm_test* PostgreSQL DB.

The test creates an ephemeral CA/server certificate, HTTPS Uvicorn, synthetic
desktop Ed25519 approval, fake Claude/Codex executables, and a real stdio MCP bridge.
It never reads server/.env, uses user records, or calls an external model/network.
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
CLAUDE_MODEL = "synthetic-claude-e2e"
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
        self.agent_stop = None
        self.agent_worker = None

    def __enter__(self):
        self.thread.start()
        for _ in range(300):
            if self.srv.started:
                return self
            time.sleep(.03)
        raise RuntimeError("synthetic HTTPS server did not start")

    def __exit__(self, *_):
        if self.agent_stop is not None:
            self.agent_stop.set()
        if self.agent_worker is not None:
            self.agent_worker.join(5)
        self.srv.should_exit = True
        self.thread.join(10)
        if self.agent_worker is not None and self.agent_worker.is_alive():
            raise RuntimeError("synthetic agent thread did not stop")
        if self.thread.is_alive():
            raise RuntimeError("synthetic TLS server thread did not stop")

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
 if not any(t['name']=='mcp__my-crm__read' for t in tools): raise RuntimeError('read-tool-missing')
 stage='state-get'; call=rpc(3,'tools/call',{'name':'mcp__my-crm__read','arguments':{'op':'state_get','params':{}}})
 if 'result' not in call or call['result'].get('isError') is not False: raise RuntimeError('state-get-denied')
 with open(EXECUTION_PATH,'a',encoding='utf-8') as log: log.write(resume+':state_get-ok\n')
 p.stdin.close(); p.wait(timeout=10)
 if p.returncode: raise RuntimeError('bridge-exit')
except Exception as exc:
 open(DIAG_PATH,'w').write(stage+':'+type(exc).__name__+':'+str(exc)[:80])
 raise
sid='synthetic-cli-session'
print(json.dumps({'type':'system','subtype':'init','session_id':sid,'model':MODEL,
 'tools':[t['name'] for t in tools],'mcp_servers':[{'name':'my-crm','status':'connected'}],
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


def desktop_approval_script(js_path, ca_path):
    js_path.write_text(r'''const https=require('node:https'),{EventEmitter}=require('node:events');
const {createConsentRuntime}=require(DESKTOP_RUNTIME);
const base=process.env.SYNTHETIC_BASE, ca=require('node:fs').readFileSync(CA_PATH), token=process.env.SYNTHETIC_TOKEN;
const post=async(path,body,authorization)=>new Promise(resolve=>{
 const raw=Buffer.from(JSON.stringify(body));const req=https.request(base+path,{method:'POST',ca,headers:{authorization,origin:process.env.SYNTHETIC_ORIGIN,cookie:process.env.SYNTHETIC_COOKIE,'content-type':'application/json','content-length':raw.length}},res=>{
  let data='';res.on('data',x=>data+=x);res.on('end',()=>{try{const parsed=JSON.parse(data);process.stderr.write(path+' '+res.statusCode+' '+(parsed.code||'ok')+'\\n');resolve({status:res.statusCode,body:parsed})}catch{process.stderr.write(path+' '+res.statusCode+' invalid\\n');resolve({status:500,body:null})}})});
 req.on('error',e=>{process.stderr.write('request network '+e.code+'\\n');resolve({status:0,body:null})});req.end(raw);
});
const pair=require('node:crypto').generateKeyPairSync('ed25519');
const url='file:///synthetic/mycrm/index.html',win={isDestroyed:()=>false,isFocused:()=>true,webContents:{
 isDevToolsOpened:()=>false,mainFrame:{parent:null,url},getURL:()=>url}};
const powerMonitor=Object.assign(new EventEmitter(),{getSystemIdleState:()=>locked?'locked':'active'});let locked=false;
const runtime=createConsentRuntime({request:post,getInstallationId:async()=>INSTALLATION,safeStorage:{isEncryptionAvailable:()=>true},
 keyFile:'/synthetic/key',loadKey:async()=>pair,app:{getPath:()=>'/synthetic'},dialog:{showMessageBox:async()=>({response:1})},
 powerMonitor,trustedWindow:()=>win,allowedUrl:url,focusWindow:async()=>true});
(async()=>{
 const ok=await runtime.handle({request_id:REQUEST_ID,device_bearer:'Bearer '+token});
 console.log(ok?'APPROVED':'DENIED');
 if(!ok)process.exit(2);
 let line='';process.stdin.setEncoding('utf8');process.stdin.on('data',async chunk=>{line+=chunk;if(line.includes('LOCK')){
  locked=true;powerMonitor.emit('lock-screen');const revoked=await runtime.invalidateOnLock();console.log(revoked?'LOCK_REVOKED':'LOCK_FAILED');process.exit(revoked?0:3);
 }});
})();
'''.replace("DESKTOP_RUNTIME", json.dumps(str(HERE.parent / "desktop/src/consent-runtime.cjs")))
       .replace("CA_PATH", json.dumps(str(ca_path)))
       .replace("INSTALLATION", json.dumps(INSTALLATION))
       .replace("REQUEST_ID", json.dumps("synthetic-e2e-session")), encoding="utf-8")


def launch_desktop_approval(approval_js, env, process_holder=None):
    """Report synthetic bridge spawn errors instead of losing them in a thread."""
    try:
        process = subprocess.Popen(["node", str(approval_js)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    except OSError as exc:
        return "BRIDGE_ERROR:" + type(exc).__name__, None
    if process_holder is not None:
        process_holder[0] = process
    result = process.stdout.readline().strip()
    if result != "APPROVED":
        process.wait(timeout=5)
        result += ":" + process.stderr.read().strip()
    return result, process


class FreechatSyntheticE2ETests(unittest.TestCase):
    def test_synthetic_server_stops_agent_before_server_thread(self):
        server = TlsServer.__new__(TlsServer)
        server.srv = type("Server", (), {"should_exit": False})()
        server.agent_stop = threading.Event()
        order = []

        class Worker:
            def join(self, _timeout):
                self_state = (server.agent_stop.is_set(), server.srv.should_exit)
                order.append(("agent", self_state))

            def is_alive(self):
                return False

        class ServerThread:
            def join(self, _timeout):
                order.append(("server", server.srv.should_exit))

            def is_alive(self):
                return False

        server.agent_worker = Worker()
        server.thread = ServerThread()
        server.__exit__(None, None, None)
        self.assertEqual(order, [("agent", (True, False)), ("server", True)])

    def test_desktop_approval_spawn_error_is_reported(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError("synthetic")):
            result, process = launch_desktop_approval("synthetic.js", {})
        self.assertEqual(result, "BRIDGE_ERROR:FileNotFoundError")
        self.assertIsNone(process)

    def test_model_approval_consumption_claude_mcp_response_resume_and_lock(self):
        self._run_isolated_provider("claude")

    def test_model_approval_consumption_codex_mcp_response_resume_and_lock(self):
        self._run_isolated_provider("codex")

    def _run_isolated_provider(self, provider_name):
        """Run each provider in its own app lifespan and readiness-patched process."""
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--run-provider", provider_name],
            cwd=str(HERE.parent), env=env, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0,
            f"isolated synthetic {provider_name} E2E failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

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
            approval_js = temp / "desktop-approval.cjs"
            desktop_approval_script(approval_js, ca)
            previous_ca = os.environ.get("SSL_CERT_FILE")
            os.environ["SSL_CERT_FILE"] = str(ca)
            uid = db.user_by_email(EMAIL)["id"]
            device = imports.device_connect(uid, "synthetic desktop")
            token, did = device["token"], device["device"]["id"]
            token_path.write_text(token, encoding="utf-8")
            token_path.chmod(0o600)
            with db.tx() as c:
                c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os,device_id) VALUES (%s,%s,'synthetic','darwin',%s)",
                          (uid, INSTALLATION, did))
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
            node = None
            node_holder = [None]
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
                        provider_exceptions = []
                        if provider_name == "codex":
                            # The provider intentionally emits generic error codes.
                            # In this synthetic child only, preserve exception type
                            # and source location so failures remain diagnosable
                            # without printing exception values or credentials.
                            from agent.chat_codex import CodexProvider
                            original_start = CodexProvider.start_turn
                            def traced_start(*args, **kwargs):
                                old_trace = sys.gettrace()
                                def trace(frame, event, arg):
                                    if (event == "exception" and "/agent/" in frame.f_code.co_filename
                                            and len(provider_exceptions) < 30):
                                        item = (Path(frame.f_code.co_filename).name,
                                                frame.f_code.co_name, frame.f_lineno, arg[0].__name__)
                                        if item not in provider_exceptions:
                                            provider_exceptions.append(item)
                                    return trace
                                sys.settrace(trace)
                                try:
                                    yield from original_start(*args, **kwargs)
                                finally:
                                    sys.settrace(old_trace)
                            CodexProvider.start_turn = traced_start
                            original_spawn = factory.process_supervisor.spawn
                            def observe_codex_spawn(argv, **kwargs):
                                try:
                                    return original_spawn(argv, **kwargs)
                                except Exception as exc:
                                    process_failures.append(f"{type(exc).__name__}:{exc}")
                                    raise
                            factory.process_supervisor.spawn = observe_codex_spawn
                        ref_store = RefStore()
                        approvals = []
                        def consent(request_id, _authorization):
                            env = dict(os.environ, SYNTHETIC_BASE=server_url, SYNTHETIC_TOKEN=token,
                                       SYNTHETIC_ORIGIN=os.environ["CRM_PUBLIC_URL"],
                                       SYNTHETIC_COOKIE="crm_session=" + main.site.session_value(uid))
                            result, p = launch_desktop_approval(approval_js, env, node_holder)
                            approvals.append(result)
                        agent_log = []
                        received = []
                        agent = agent_chat.ChatAgent(srv.ws, token, ref_store=ref_store,
                            agent_version="synthetic", stopping=stop, consent_request=consent,
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
                        srv.agent_stop = stop
                        srv.agent_worker = worker
                        worker.start()
                        with httpx.Client(base_url=server_url, verify=str(ca), timeout=10,
                                          headers={"origin": os.environ["CRM_PUBLIC_URL"]},
                                          cookies={"crm_session": main.site.session_value(uid)}) as h:
                            for _ in range(100):
                                if agent.connects and webchat.hub.connected(uid, did): break
                                time.sleep(.05)
                            self.assertTrue(webchat.hub.connected(uid, did), f"agent WebSocket did not connect: {agent_log}")
                            created = h.post("/api/chat/grants", json={"device_id": did, "provider": provider_name,
                                "model": model, "request_id": SESSION_REQUEST})
                            self.assertEqual(created.status_code, 201, created.text)
                            for _ in range(100):
                                if approvals: break
                                time.sleep(.05)
                            self.assertEqual(approvals, ["APPROVED"],
                                f"PC consent bridge not observed: connects={agent.connects}, logs={agent_log}, received={received}, "
                                f"connected={webchat.hub.connected(uid,did)}, dev_binding={(webchat.hub.dev(uid,did).dev['user_id'],webchat.hub.dev(uid,did).dev['id']) if webchat.hub.dev(uid,did) else None}")
                            with db.tx() as c:
                                state = c.execute("SELECT state FROM chat_provider_grants WHERE user_id=%s AND request_id=%s",
                                                  (uid, SESSION_REQUEST)).fetchone()["state"]
                            self.assertEqual(state, "approved")
                            session = h.post("/api/chat/sessions", json={"operation":"new", "device_id":did,
                                "provider":provider_name, "model":model, "client_session_id":SESSION_REQUEST})
                            self.assertEqual(session.status_code, 201, session.text)
                            sid = session.json()["session_id"]
                            with db.tx() as c:
                                consumed = c.execute("SELECT state FROM chat_provider_grants WHERE user_id=%s AND request_id=%s",
                                                     (uid, SESSION_REQUEST)).fetchone()["state"]
                            self.assertEqual(consumed, "consumed")
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
                                    f"process_failures={process_failures}, provider_exceptions={provider_exceptions}, agent_log={agent_log}")
                                messages = h.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
                                results.append([m["body"] for m in messages if m["turn_id"] == tid and m["role"] == "assistant"])
                            self.assertEqual(results, [["Synthetic state loaded; turn resumed."]] * 2)
                            self.assertEqual(cli_executions.read_text(encoding="utf-8").splitlines(),
                                             ["new:state_get-ok", "resume:state_get-ok"])
                            self.assertEqual(len(approvals), 1, "resume must not ask for a second approval")
                            node = node_holder[0]
                            self.assertIsNotNone(node)
                            node.stdin.write("LOCK\n"); node.stdin.flush()
                            self.assertEqual(node.stdout.readline().strip(), "LOCK_REVOKED")
                            node.wait(timeout=5)
                            with db.tx() as c:
                                key_state = c.execute("SELECT state FROM desktop_consent_keys WHERE user_id=%s AND installation_id=%s",
                                    (uid, INSTALLATION)).fetchone()["state"]
                            self.assertEqual(key_state, "revoked")
            finally:
                stop.set()
                if agent:
                    for th in list(agent.threads): th.join(2)
                node = node or node_holder[0]
                if node and node.poll() is None:
                    node.kill(); node.wait()
                with db.tx() as c:
                    c.execute("DELETE FROM admin_audit WHERE actor_id=%s OR target_id=%s", (uid, uid))
                db.user_delete(uid)
                db.close()
                if previous_ca is None: os.environ.pop("SSL_CERT_FILE", None)
                else: os.environ["SSL_CERT_FILE"] = previous_ca


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--run-provider" and sys.argv[2] in ("claude", "codex"):
        db.init_schema()
        try:
            FreechatSyntheticE2ETests()._run_provider(sys.argv[2])
        finally:
            db.close()
    else:
        db.init_schema()
        unittest.main()
