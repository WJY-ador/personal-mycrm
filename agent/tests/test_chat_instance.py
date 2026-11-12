"""J-F7: one resident chat per home; only the kernel-reported lock holder of the previous run is ended."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent import chat_instance
from agent.chat_instance import ChatInstance, InstanceUnavailable

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOLDER = r"""
import os, signal, sys, time
sys.path.insert(0, sys.argv[1])
from agent.chat_instance import ChatInstance
if sys.argv[3] == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
ChatInstance(sys.argv[2]).claim()
print("held", flush=True)
time.sleep(60)
"""


@unittest.skipUnless(ChatInstance.supported(), "POSIX record locks only (chat does not run on Windows)")
class ChatInstanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.locks = self.tmp.name

    def holder(self, mode="default"):
        proc = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, ROOT, self.locks, mode],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(5), proc.stdout.close()))
        self.assertEqual(proc.stdout.readline().strip(), b"held")
        return proc

    def test_free_lock_is_claimed_and_released_without_signals(self):
        sent = []
        inst = ChatInstance(self.locks, kill=lambda pid, sig: sent.append((pid, sig))).claim()
        with open(os.path.join(self.locks, chat_instance.LOCK_NAME)) as f:
            self.assertEqual(f.read(), str(os.getpid()))
        self.assertIsNone(inst.reaped)
        inst.release()
        self.assertEqual(sent, [])
        ChatInstance(self.locks).claim().release()   # claimable again

    def test_kernel_reports_the_holder_pid_not_the_file_content(self):
        proc = self.holder()
        path = os.path.join(self.locks, chat_instance.LOCK_NAME)
        with open(path, "w") as f:
            f.write("1")   # a stale or forged pid in the file plays no part
        fd = os.open(path, os.O_RDWR)
        try:
            self.assertEqual(chat_instance.holder_pid(fd), proc.pid)
        finally:
            os.close(fd)
        proc.kill()
        proc.wait(5)
        fd = os.open(path, os.O_RDWR)
        try:
            self.assertIsNone(chat_instance.holder_pid(fd), "a dead holder holds nothing")
        finally:
            os.close(fd)

    def test_previous_chat_is_ended_with_sigterm_and_the_lock_taken(self):
        proc = self.holder()
        sent = []
        def kill(pid, sig):
            sent.append((pid, sig))
            os.kill(pid, sig)
        inst = ChatInstance(self.locks, kill=kill, term_wait=5, poll=0.02).claim()
        self.addCleanup(inst.release)
        self.assertEqual(sent, [(proc.pid, signal.SIGTERM)])
        self.assertEqual(inst.reaped, proc.pid)
        self.assertEqual(proc.wait(5), -signal.SIGTERM)

    def test_a_holder_that_ignores_sigterm_gets_one_sigkill(self):
        proc = self.holder("ignore-term")
        sent = []
        def kill(pid, sig):
            sent.append(sig)
            os.kill(pid, sig)
        inst = ChatInstance(self.locks, kill=kill, term_wait=0.3, kill_wait=5, poll=0.02).claim()
        self.addCleanup(inst.release)
        self.assertEqual(sent, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(proc.wait(5), -signal.SIGKILL)

    def test_a_holder_that_never_ends_refuses_the_claim(self):
        proc = self.holder()
        sent = []
        with self.assertRaises(InstanceUnavailable):
            ChatInstance(self.locks, kill=lambda pid, sig: sent.append((pid, sig)),
                         term_wait=0.1, kill_wait=0.1, poll=0.02).claim()
        self.assertEqual(sent, [(proc.pid, signal.SIGTERM), (proc.pid, signal.SIGKILL)])
        self.assertIsNone(proc.poll(), "only the signals the fake recorded were sent")

    # R-J4: the lock path must be our own regular file. Anything else is refused before any lock, signal or truncate.
    def refused(self, reason="unsafe"):
        sent = []
        with self.assertRaises(InstanceUnavailable) as caught:
            ChatInstance(self.locks, kill=lambda pid, sig: sent.append((pid, sig)),
                         term_wait=0.1, kill_wait=0.1, poll=0.02).claim()
        self.assertEqual(str(caught.exception), reason)
        self.assertEqual(sent, [], "no signal is sent")

    def test_symlink_to_another_lock_holder_is_refused_without_a_signal(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        proc = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, ROOT, other.name, "default"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(5), proc.stdout.close()))
        self.assertEqual(proc.stdout.readline().strip(), b"held")
        target = os.path.join(other.name, chat_instance.LOCK_NAME)
        with open(target) as f:
            before = f.read()
        os.symlink(target, os.path.join(self.locks, chat_instance.LOCK_NAME))
        self.refused()
        self.assertIsNone(proc.poll(), "the other holder is untouched")
        with open(target) as f:
            self.assertEqual(f.read(), before, "the target file is not truncated")

    def test_directory_is_refused(self):
        os.mkdir(os.path.join(self.locks, chat_instance.LOCK_NAME))
        self.refused()

    def test_fifo_is_refused_without_blocking(self):
        os.mkfifo(os.path.join(self.locks, chat_instance.LOCK_NAME))
        start = time.monotonic()
        self.refused()
        self.assertLess(time.monotonic() - start, 5)

    def test_file_owned_by_someone_else_is_refused(self):
        path = os.path.join(self.locks, chat_instance.LOCK_NAME)
        with open(path, "w") as f:
            f.write("keep")
        with patch.object(chat_instance.os, "geteuid", lambda: os.stat(path).st_uid + 1):
            self.refused()
        with open(path) as f:
            self.assertEqual(f.read(), "keep")

    def test_permission_error_is_unavailable_not_a_crash(self):
        self.holder()
        def kill(pid, sig):
            raise PermissionError()
        with self.assertRaises(InstanceUnavailable):
            ChatInstance(self.locks, kill=kill, term_wait=0.1, kill_wait=0.1, poll=0.02).claim()


class ChatInstanceUnsupportedTest(unittest.TestCase):
    def test_windows_claims_nothing(self):
        with patch.object(ChatInstance, "supported", staticmethod(lambda: False)):
            inst = ChatInstance(tempfile.gettempdir(), kill=lambda *a: self.fail("no signal")).claim()
            self.assertIsNone(inst.reaped)
            inst.release()


if __name__ == "__main__":
    unittest.main()
