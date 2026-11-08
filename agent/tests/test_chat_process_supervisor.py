import os
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from agent.chat_process_supervisor import MacOSProcessSupervisor, ProcessContainmentUnavailable


class MacOSProcessSupervisorTest(unittest.TestCase):
    def test_failed_group_signal_with_live_peer_is_not_success(self):
        class Proc:
            pid = 424242
            returncode = None
            def wait(self, timeout=None):
                self.returncode = 0
                return 0
        proc = Proc()
        supervisor = MacOSProcessSupervisor(waitid=lambda *_args: types.SimpleNamespace(si_pid=proc.pid))
        supervisor._states[proc] = {"pid": proc.pid, "reaped": False}
        with patch.object(supervisor, "_signal_group", return_value=False), \
             patch.object(supervisor, "_has_live_group_peers", return_value=True):
            with self.assertRaises(ProcessContainmentUnavailable):
                supervisor.finish(proc, timeout=0)

    def test_waits_for_leader_without_reaping_then_cleans_same_process_group(self):
        if sys.platform != "darwin":
            self.skipTest("macOS waitid/PGID lifetime behavior")
        with tempfile.TemporaryDirectory() as root:
            pid_file = os.path.join(root, "descendant.pid")
            script = (
                "import subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                f"open({pid_file!r},'w').write(str(p.pid))"
            )
            supervisor = MacOSProcessSupervisor(popen=subprocess.Popen)
            proc = supervisor.spawn([sys.executable, "-c", script], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result = supervisor.finish(proc, timeout=3)
            # The supervisor cleans a cooperative same-group child but does not
            # claim containment: a descendant could leave this process group.
            self.assertEqual(result, (0, False))
            with open(pid_file, encoding="utf-8") as handle:
                child_pid = int(handle.read())
            for _ in range(100):
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(.01)
            else:
                state = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(child_pid)],
                                       capture_output=True, text=True, check=False).stdout.strip()
                self.assertFalse(state, f"synthetic descendant still exists: {state}")

    def test_cannot_claim_tree_clean_when_descendant_leaves_process_group(self):
        if sys.platform != "darwin":
            self.skipTest("macOS waitid/PGID lifetime behavior")
        with tempfile.TemporaryDirectory() as root:
            pid_file = os.path.join(root, "escaped-descendant.pid")
            script = (
                "import subprocess,sys; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                f"open({pid_file!r},'w').write(str(p.pid))"
            )
            supervisor = MacOSProcessSupervisor(popen=subprocess.Popen)
            proc = supervisor.spawn([sys.executable, "-c", script], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rc, tree_clean = supervisor.finish(proc, timeout=3)
            self.assertEqual(rc, 0)
            self.assertFalse(tree_clean)
            with open(pid_file, encoding="utf-8") as handle:
                escaped_pid = int(handle.read())
            try:
                os.kill(escaped_pid, 0)
            except ProcessLookupError:
                self.fail("fixture did not escape its process group")
            finally:
                try:
                    os.kill(escaped_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_sandbox_exec_does_not_prevent_forked_child_from_leaving_group(self):
        if sys.platform != "darwin":
            self.skipTest("macOS sandbox-exec behavior")
        # Broad file-read is required by this Python build's runtime. It is
        # intentionally not acceptable as a production sandbox policy.
        profile = (
            '(version 1) (deny default) '
            '(allow process-exec* (subpath "/opt/homebrew")) '
            '(allow process-fork) (allow file-read*) '
            '(deny process-exec* (literal "/bin/sh"))'
        )
        code = (
            "import os,time; pid=os.fork(); "
            "(os.setsid(),print(os.getpid(),flush=True),time.sleep(30)) if pid==0 "
            "else time.sleep(30)"
        )
        supervisor = MacOSProcessSupervisor(popen=subprocess.Popen)
        proc = supervisor.spawn(["/usr/bin/sandbox-exec", "-p", profile,
                                 sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        escaped_pid = int(proc.stdout.readline())
        try:
            supervisor.terminate_tree(proc)
            # sandbox-exec leaves fork/setsid usable under this policy, so
            # group cancellation cannot reach the detached synthetic child.
            os.kill(escaped_pid, 0)
        finally:
            try:
                os.kill(escaped_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.stdout.close()

    def test_sandbox_exec_profile_blocks_shell_and_writes_but_read_rule_is_global(self):
        if sys.platform != "darwin":
            self.skipTest("macOS sandbox-exec behavior")
        profile = (
            '(version 1) (deny default) '
            '(allow process-exec* (subpath "/opt/homebrew")) '
            '(allow process-fork) (allow file-read*) '
            '(deny process-exec* (literal "/bin/sh"))'
        )
        with tempfile.TemporaryDirectory() as root:
            write_target = os.path.join(root, "blocked-write")
            cases = {
                "shell": 'import subprocess; subprocess.run(["/bin/sh","-c","echo shell-ran"])',
                "read": 'open("/etc/hosts").read(); print("system-file-readable")',
                "write": f'open({write_target!r},"w").write("synthetic")',
            }
            results = {}
            for name, code in cases.items():
                results[name] = subprocess.run(
                    ["/usr/bin/sandbox-exec", "-p", profile, sys.executable, "-c", code],
                    capture_output=True, text=True, timeout=5, check=False)
            self.assertNotEqual(results["shell"].returncode, 0)
            self.assertEqual(results["read"].returncode, 0)
            self.assertIn("system-file-readable", results["read"].stdout)
            self.assertNotEqual(results["write"].returncode, 0)
            self.assertFalse(os.path.exists(write_target))

    def test_fails_closed_when_waitid_wnowait_is_unavailable(self):
        supervisor = MacOSProcessSupervisor(popen=subprocess.Popen, waitid=None)
        with self.assertRaises(ProcessContainmentUnavailable):
            supervisor.spawn([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_never_signals_group_after_leader_was_reaped_outside_supervisor(self):
        if sys.platform != "darwin":
            self.skipTest("macOS waitid/PGID lifetime behavior")
        supervisor = MacOSProcessSupervisor(popen=subprocess.Popen)
        proc = supervisor.spawn([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait(timeout=3)  # Simulate a caller that violates supervisor ownership.
        calls = []
        supervisor._signal_group = lambda _proc, sig: calls.append(sig)
        with self.assertRaises(ProcessContainmentUnavailable):
            supervisor.terminate_tree(proc)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
