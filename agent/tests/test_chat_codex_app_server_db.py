"""Opt-in synthetic DB integration for the disabled app-server candidate.

This does not exercise the network device authorization or a real Codex model.
"""
import json
import os
import sys
import tempfile
import urllib.parse
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from agent.chat_codex import CodexProvider
from agent.chat_codex_app_provider import AppServerCandidateProvider
from agent.tests.test_chat_codex_dynamic import SyntheticClient
from agent.tests.test_chat_codex_app_server import SyntheticSupervisor

DB_URL = os.environ.get('CRM_SYNTH_DB_E2E_URL', '')
parts = urllib.parse.urlsplit(DB_URL)
SAFE_DB = parts.hostname in ('localhost', '127.0.0.1', '::1') and parts.path.lstrip('/').startswith('crm_test_')


@unittest.skipUnless(SAFE_DB, 'requires explicit local synthetic database')
class CodexApprovalDatabaseTest(unittest.TestCase):
    def test_child_bridge_pending_confirm_then_apply_once(self):
        os.environ['DATABASE_URL'] = DB_URL
        os.environ['CRM_DEV'] = '1'
        os.environ['CRM_SESSION_SECRET'] = 'synthetic-approval-only-secret'
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
        import db
        import main  # Registers the existing facade operations.
        import webchat
        db.init_schema()
        uid = db.user_by_email('synthetic-' + uuid.uuid4().hex + '@example.invalid')['id']
        try:
            db.display_name_set(uid, 'Synthetic')
            sid, tid = webchat._id('cs'), webchat._id('ct')
            with db.tx() as c:
                c.execute("INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version) VALUES (%s,%s,'synthetic-device','codex','synthetic-model','synthetic-client',2)", (sid, uid))
                c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,'synthetic-turn')", (tid, sid))
            record = db.record_add(uid, 'Synthetic record', 'before synthetic after')
            params = {'record_id': record['id'], 'expected_revision': 1, 'old': 'before', 'new': 'changed'}
            client = SyntheticClient()
            client.auth = replace(client.auth, user_id=uid, device_id='synthetic-device',
                session_id=sid, turn_id=tid, model='synthetic-model',
                tools=MappingProxyType({'mcp__my-crm__find':'read', 'mcp__my-crm__record_edit':'decide'}))
            # The HTTP device grant is not part of this test. Calls below invoke
            # the real server approval function after the existing bridge checks.
            client.call_mcp = lambda auth, surface, args, *, op=None, bind='': webchat.approval_prepare(uid, sid, tid, op, args)
            with tempfile.TemporaryDirectory(prefix='mycrm-synthetic-auth-') as home, \
                 patch('webchat._require_consumed_session_consent'), \
                 patch('webchat.chat_mcp_enabled', return_value=True), \
                 patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', True), \
                 patch('agent.chat_codex_app_provider._cli_version_supported', return_value=True), \
                 patch.object(CodexProvider, 'is_available', return_value=True):
                os.chmod(home, 0o700)
                auth_home = os.path.join(home, 'codex-auth')
                os.mkdir(auth_home, 0o700)
                auth_file = os.path.join(auth_home, 'auth.json')
                with open(auth_file, 'w', encoding='utf-8') as handle:
                    handle.write('synthetic')
                os.chmod(auth_file, 0o600)
                env = {'CODEX_HOME':auth_home, 'HOME':home, 'PATH':'/usr/bin:/bin',
                       'MYCRM_SYNTHETIC_ARGUMENTS':json.dumps({'op':'record_edit','params':params,'bind':'synthetic'})}
                context = SimpleNamespace(codex_home=auth_home, cwd=home, runtime_dir=home,
                    session_id=sid, turn_id=tid, device_id='synthetic-device', model='synthetic-model', env=env)
                base = object.__new__(CodexProvider)
                base.cli_path, base.model = '/usr/bin/true', 'synthetic-model'
                base.launch_context = context
                base.launch_verifier = SimpleNamespace(client=client, verify_codex_grant=lambda _: True)
                base.process_supervisor, base.timeout = SyntheticSupervisor(), 3
                provider = AppServerCandidateProvider(base, agent_home=home)
                events = list(provider.start_turn('request review'))
                self.assertEqual(events[-1], ('done', {}))
                cards = webchat.approvals_list(uid, sid)
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0]['status'], 'pending')
                self.assertEqual(db.record_get(uid, record['id'])['body'], 'before synthetic after')
                webchat.approval_confirm(uid, sid, cards[0]['id'])
                self.assertEqual(db.record_get(uid, record['id'])['body'], 'changed synthetic after')
                with self.assertRaises(db.CrmError):
                    webchat.approval_confirm(uid, sid, cards[0]['id'])
        finally:
            db.user_delete(uid)
            db.close()


if __name__ == '__main__':
    unittest.main()
