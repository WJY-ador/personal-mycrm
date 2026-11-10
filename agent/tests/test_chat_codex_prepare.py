"""Cancellation and lifecycle of managed CLI preparation."""
import os
import sys
import tempfile
import threading
import time
import unittest

from agent.chat_codex_prepare import PreparationCancelled, run_preparation


class ManagedPreparationTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and hasattr(os, 'WNOWAIT'), 'macOS process group required')
    def test_cancel_stops_delayed_child_before_it_commits(self):
        with tempfile.TemporaryDirectory() as home:
            marker = os.path.join(home, 'should-not-exist')
            cancel = threading.Event()
            code = ('import pathlib,sys,time; print("started",flush=True); '
                    'time.sleep(2); pathlib.Path(sys.argv[1]).write_text("bad")')
            timer = threading.Timer(0.15, cancel.set)
            timer.start()
            self.addCleanup(timer.cancel)
            with self.assertRaises(PreparationCancelled):
                run_preparation([sys.executable, '-c', code, marker], cancelled=cancel.is_set,
                                timeout=5, poll_interval=0.03)
            self.assertFalse(os.path.exists(marker))

    @unittest.skipUnless(sys.platform == 'darwin' and hasattr(os, 'WNOWAIT'), 'macOS process group required')
    def test_completed_preparation_returns_only_expected_fields(self):
        code = 'print(\'{"path":"/tmp/codex","version":"0.168.0"}\')'
        result = run_preparation([sys.executable, '-c', code], cancelled=lambda: False, timeout=5)
        self.assertEqual(result, {'path':'/tmp/codex', 'version':'0.168.0'})

    @unittest.skipUnless(sys.platform == 'darwin' and hasattr(os, 'WNOWAIT'), 'macOS process group required')
    def test_rejects_unexpected_or_oversized_output(self):
        for code in ('print(\'{"path":"/tmp/codex","version":"0.168.0","secret":"x"}\')',
                     'print("x" * 5000)'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                run_preparation([sys.executable, '-c', code], cancelled=lambda: False, timeout=5)

    @unittest.skipUnless(sys.platform == 'darwin' and hasattr(os, 'WNOWAIT'), 'macOS process group required')
    def test_cancel_interrupts_real_prepare_command_and_cleans_staged_file(self):
        with tempfile.TemporaryDirectory() as home:
            stage = os.path.join(home, 'synthetic-stage')
            cancel = threading.Event()
            code = '''
import os,sys,time
from unittest.mock import patch
from agent import cli
def prepare(*args):
    with open(sys.argv[2], 'w') as staged:
        staged.write('incomplete')
    try:
        time.sleep(10)
    finally:
        os.unlink(sys.argv[2])
with patch('agent.cli._config.load', return_value={}), \\
     patch('agent.cli.Ctx.keystore', return_value=object()), \\
     patch('agent.chat_codex_update.resolve_managed_cli', side_effect=prepare):
    cli.main(['--home', sys.argv[1], 'codex-prepare-managed'])
'''
            def watch_stage():
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    if os.path.exists(stage):
                        cancel.set()
                        return
                    time.sleep(0.01)
            watcher = threading.Thread(target=watch_stage, daemon=True)
            watcher.start()
            with self.assertRaises(PreparationCancelled):
                run_preparation([sys.executable, '-c', code, home, stage],
                                cancelled=cancel.is_set, timeout=5, poll_interval=0.02)
            watcher.join(timeout=1)
            self.assertTrue(cancel.is_set())
            self.assertFalse(os.path.exists(stage))

    @unittest.skipUnless(sys.platform == 'darwin' and hasattr(os, 'WNOWAIT'), 'macOS process group required')
    def test_pre_cancel_does_not_start_preparation(self):
        with tempfile.TemporaryDirectory() as home:
            marker = os.path.join(home, 'should-not-exist')
            code = 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("bad")'
            with self.assertRaises(PreparationCancelled):
                run_preparation([sys.executable, '-c', code, marker], cancelled=lambda: True,
                                timeout=5, poll_interval=0.03)
            self.assertFalse(os.path.exists(marker))
