"""Synthetic process-level tests for the disabled app-server candidate."""
import os
import subprocess
import sys
import unittest

from agent.chat_codex_dynamic import AppServerProcess
from agent.tests import test_chat_codex_dynamic as fixtures


CHILD = r'''
import json,sys,os
def read(): return json.loads(sys.stdin.buffer.readline())
def send(x): print(json.dumps(x),flush=True)
thread='11111111-1111-4111-8111-111111111111'
turn='22222222-2222-4222-8222-222222222222'
x=read(); send({'id':x['id'],'result':{}})
read()
x=read(); send({'id':x['id'],'result':{'thread':{'id':thread}}})
x=read(); send({'id':x['id'],'result':{'turn':{'id':turn}}})
arguments=json.loads(os.environ.get('MYCRM_SYNTHETIC_ARGUMENTS',
 '{"op":"candidate_decide","params":{},"bind":"abc"}'))
send({'id':10,'method':'item/tool/call','params':{'threadId':thread,'turnId':turn,
 'callId':'one','tool':'mycrm_decide','arguments':arguments}})
x=read()
assert x['id']==10 and x['result']['success']
send({'method':'item/completed','params':{'threadId':thread,'turnId':turn,
 'item':{'type':'agentMessage','text':'confirmation pending'}}})
send({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'completed'}}})
sys.stdin.buffer.read()
'''


class SyntheticSupervisor:
    def __init__(self): self.proc = None; self.stopped = False
    def spawn(self, argv, **kwargs):
        self.proc = subprocess.Popen([sys.executable, '-u', '-c', CHILD], **kwargs)
        return self.proc
    def terminate_tree(self, proc):
        proc.terminate()
        proc.wait(timeout=3)
        self.stopped = True


class AppServerProcessTest(unittest.TestCase):
    def test_pending_confirmation_via_child_process_and_authenticated_bridge(self):
        fixture = fixtures.DynamicToolRelayTest()
        fixture.setUp()
        supervisor = SyntheticSupervisor()
        runner = AppServerProcess(supervisor, fixture.relay, lambda: True, timeout=3)
        events = list(runner.run(['synthetic'], cwd=os.path.abspath('.'), env={},
            model='synthetic', text='ask for confirmation'))
        self.assertTrue(supervisor.stopped)
        self.assertEqual(events[-1], ('done', {}))
        self.assertEqual(fixture.client.calls, [('decide', 'candidate_decide', {}, 'abc')])
        self.assertIn(('delta', {'text': 'confirmation pending'}), events)

    def test_cleanup_failure_never_emits_done(self):
        class CleanupFailure(SyntheticSupervisor):
            def terminate_tree(self, proc):
                super().terminate_tree(proc)
                raise RuntimeError('cleanup unconfirmed')
        fixture = fixtures.DynamicToolRelayTest()
        fixture.setUp()
        runner = AppServerProcess(CleanupFailure(), fixture.relay, lambda: True, timeout=3)
        events = []
        with self.assertRaisesRegex(RuntimeError, 'cleanup unconfirmed'):
            for event in runner.run(['synthetic'], cwd=os.path.abspath('.'), env={},
                                    model='synthetic', text='ask for confirmation'):
                events.append(event)
        self.assertNotIn(('done', {}), events)


if __name__ == '__main__':
    unittest.main()
