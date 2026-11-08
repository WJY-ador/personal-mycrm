"""Opt-in synthetic DB integration for the disabled app-server candidate.

This does not exercise the network device authorization or a real Codex model.
"""
import json
import os
import sys
import urllib.parse
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from agent.chat_codex_dynamic import AppServerProcess, DynamicToolRelay
from agent.chat_mcp_bridge import McpStdioBridge
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
            bridge = McpStdioBridge(client, '/api/chat/launch-authorization', sid, tid,
                                    'codex', 'synthetic-model', 'synthetic-device')
            runner = AppServerProcess(SyntheticSupervisor(), DynamicToolRelay(bridge), lambda: True, timeout=3)
            env = {'MYCRM_SYNTHETIC_ARGUMENTS': json.dumps({'op':'record_edit','params':params,'bind':'synthetic'})}
            with patch('webchat._require_consumed_session_consent'), patch('webchat.chat_mcp_enabled', return_value=True):
                events = list(runner.run(['synthetic'], cwd=os.path.abspath('.'), env=env,
                                         model='synthetic-model', text='request review'))
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
