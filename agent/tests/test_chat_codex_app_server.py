"""Synthetic process-level tests for the disabled app-server candidate."""
import os
import subprocess
import sys
import threading
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
x=read()
if x.get('method')=='account/read':
 send({'id':x['id'],'result':{'account':{'type':'chatgpt'}}}); x=read()
send({'id':x['id'],'result':{'thread':{'id':thread}}})
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
    def test_expired_or_missing_account_is_rejected_before_thread_start(self):
        child = r'''
import json,sys
def read(): return json.loads(sys.stdin.buffer.readline())
def send(x): print(json.dumps(x),flush=True)
x=read(); send({'id':x['id'],'result':{}})
read()
x=read(); assert x['method']=='account/read'; send({'id':x['id'],'result':{'account':None}})
sys.stdin.buffer.read()
'''
        class NoAccountSupervisor(SyntheticSupervisor):
            def spawn(self, argv, **kwargs):
                self.proc = subprocess.Popen([sys.executable, '-u', '-c', child], **kwargs)
                return self.proc
        fixture = fixtures.DynamicToolRelayTest()
        fixture.setUp()
        supervisor = NoAccountSupervisor()
        runner = AppServerProcess(supervisor, fixture.relay, lambda: True, timeout=3)
        with self.assertRaisesRegex(ValueError, 'login-required'):
            list(runner.run(['synthetic'], cwd=os.path.abspath('.'), env={},
                model='synthetic', text='hello', require_authenticated_account=True))
        self.assertTrue(supervisor.stopped)

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

    def test_stop_interrupts_running_process_without_completion(self):
        class IdleSupervisor(SyntheticSupervisor):
            def spawn(self, argv, **kwargs):
                self.proc = subprocess.Popen([sys.executable, '-u', '-c', 'import time; time.sleep(30)'], **kwargs)
                ready.set()
                return self.proc
        ready = threading.Event()
        fixture = fixtures.DynamicToolRelayTest()
        fixture.setUp()
        supervisor = IdleSupervisor()
        runner = AppServerProcess(supervisor, fixture.relay, lambda: True, timeout=5)
        events, errors = [], []
        def run():
            try:
                events.extend(runner.run(['synthetic'], cwd=os.path.abspath('.'), env={},
                                         model='synthetic', text='hello'))
            except ValueError as error:
                errors.append(str(error))
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(ready.wait(3))
        runner.stop()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(supervisor.stopped)
        self.assertNotIn(('done', {}), events)
        self.assertTrue(errors)

    def test_revoked_consent_terminates_idle_child_without_completion(self):
        class IdleSupervisor(SyntheticSupervisor):
            def spawn(self, argv, **kwargs):
                self.proc = subprocess.Popen([sys.executable, '-u', '-c', 'import time; time.sleep(30)'], **kwargs)
                ready.set()
                return self.proc
        ready, revoked = threading.Event(), threading.Event()
        fixture = fixtures.DynamicToolRelayTest()
        fixture.setUp()
        supervisor = IdleSupervisor()
        runner = AppServerProcess(supervisor, fixture.relay, lambda: not revoked.is_set(), timeout=5)
        events, errors = [], []
        def run():
            try:
                events.extend(runner.run(['synthetic'], cwd=os.path.abspath('.'), env={},
                                         model='synthetic', text='hello'))
            except ValueError as error:
                errors.append(str(error))
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(ready.wait(3))
        revoked.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(supervisor.stopped)
        self.assertIsNotNone(supervisor.proc.poll())
        self.assertNotIn(('done', {}), events)
        self.assertIn('consent-revoked', errors)

    def test_revoked_consent_during_active_turn_terminates_child(self):
        active_child = r'''
import json,sys,time
def read(): return json.loads(sys.stdin.buffer.readline())
def send(x): print(json.dumps(x),flush=True)
x=read(); send({'id':x['id'],'result':{}})
read()
x=read(); send({'id':x['id'],'result':{'thread':{'id':'11111111-1111-4111-8111-111111111111'}}})
x=read(); send({'id':x['id'],'result':{'turn':{'id':'22222222-2222-4222-8222-222222222222'}}})
time.sleep(30)
'''
        class ActiveSupervisor(SyntheticSupervisor):
            def spawn(self, argv, **kwargs):
                self.proc = subprocess.Popen([sys.executable, '-u', '-c', active_child], **kwargs)
                return self.proc
        active, revoked = threading.Event(), threading.Event()
        fixture = fixtures.DynamicToolRelayTest()
        fixture.setUp()
        supervisor = ActiveSupervisor()
        runner = AppServerProcess(supervisor, fixture.relay, lambda: not revoked.is_set(), timeout=5)
        events, errors = [], []
        def run():
            try:
                for event in runner.run(['synthetic'], cwd=os.path.abspath('.'), env={},
                                        model='synthetic', text='hello'):
                    events.append(event)
                    if event[0] == 'session_ref':
                        active.set()
            except ValueError as error:
                errors.append(str(error))
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(active.wait(3))
        revoked.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(supervisor.stopped)
        self.assertIsNotNone(supervisor.proc.poll())
        self.assertNotIn(('done', {}), events)
        self.assertIn('consent-revoked', errors)
        self.assertEqual(fixture.client.calls, [])


if __name__ == '__main__':
    unittest.main()
