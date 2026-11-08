"""macOS process-group cleanup for subscription CLI candidates.

The retained leader prevents PGID reuse during group signalling. This is best-effort
cleanup, not a sandbox: descendants that deliberately leave the group cannot be
enumerated or contained here. `finish` never certifies a complete process tree.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import weakref


class ProcessContainmentUnavailable(RuntimeError):
    pass


class MacOSProcessSupervisor:
    """Best-effort cleanup while preserving a zombie group leader as a PGID pin.

    The boolean from `finish` means complete descendant-tree cleanup was verified.
    It remains false because a descendant can call setsid(). The mechanism is
    intentionally unavailable off macOS or without WNOWAIT.
    """

    def __init__(self, *, popen=subprocess.Popen, waitid=os.waitid if hasattr(os, "waitid") else None):
        self._popen = popen
        self._waitid = waitid
        self._lock = threading.RLock()
        self._states = weakref.WeakKeyDictionary()

    def _supported(self):
        return (sys.platform == "darwin" and callable(self._waitid)
                and hasattr(os, "WNOWAIT") and hasattr(os, "P_PID"))

    def spawn(self, argv, **kwargs):
        if not self._supported():
            raise ProcessContainmentUnavailable("stable-process-group-pin-unavailable")
        if "start_new_session" in kwargs or "preexec_fn" in kwargs:
            raise ProcessContainmentUnavailable("process-session-override")
        kwargs["start_new_session"] = True
        kwargs["shell"] = False
        kwargs["close_fds"] = True
        proc = self._popen(argv, **kwargs)
        with self._lock:
            self._states[proc] = {"pid": proc.pid, "reaped": False}
        return proc

    def _observe_exit(self, proc, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                info = self._waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                raise ProcessContainmentUnavailable("leader-reaped-outside-supervisor") from None
            if info is not None and info.si_pid == proc.pid:
                return info
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    @staticmethod
    def _signal_group(proc, sig):
        # The unreaped leader pins its process-group ID, so this cannot target a
        # recycled group even if the leader has already exited.
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            # A group containing only an already-dead leader can become
            # unsignalable. Treat this as unverified rather than escalating.
            return False
        return True

    @staticmethod
    def _has_live_group_peers(proc):
        """Return whether ps sees live members besides the retained zombie leader.

        macOS can report EPERM when signalling a group whose leader is already a
        zombie. That is harmless only if the group has no other live members.
        None means the check failed and callers must fail closed.
        """
        try:
            result = subprocess.run(["/bin/ps", "-axo", "pid=,pgid=,stat="],
                                    capture_output=True, text=True, timeout=1.0, check=False)
            if result.returncode != 0:
                return None
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) < 3:
                    continue
                try:
                    pid, pgid = int(fields[0]), int(fields[1])
                except ValueError:
                    return None
                if pgid == proc.pid and pid != proc.pid and not fields[2].startswith("Z"):
                    return True
            return False
        except Exception:
            return None

    def _signal_after_leader_exit(self, proc, sig):
        if self._signal_group(proc, sig):
            return
        peers = self._has_live_group_peers(proc)
        if peers is not False:
            raise ProcessContainmentUnavailable("process-group-signal-unconfirmed")

    def finish(self, proc, timeout):
        with self._lock:
            state = self._states.get(proc)
            if not state or state["pid"] != proc.pid:
                raise ProcessContainmentUnavailable("untracked-process")
            if state["reaped"]:
                return proc.returncode, False
            info = self._observe_exit(proc, timeout)
            if info is None:
                if not self._signal_group(proc, signal.SIGTERM):
                    raise ProcessContainmentUnavailable("process-group-term-failed")
                info = self._observe_exit(proc, 0.5)
            if info is None:
                if not self._signal_group(proc, signal.SIGKILL):
                    raise ProcessContainmentUnavailable("process-group-kill-failed")
                info = self._observe_exit(proc, 1.0)
            if info is None:
                raise ProcessContainmentUnavailable("leader-did-not-exit")
            self._signal_after_leader_exit(proc, signal.SIGTERM)
            time.sleep(0.05)
            self._signal_after_leader_exit(proc, signal.SIGKILL)
            try:
                rc = proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                raise ProcessContainmentUnavailable("leader-reap-timeout") from None
            state["reaped"] = True
            # Process groups do not prevent a descendant from calling setsid().
            # Never report a complete descendant-tree guarantee from this method.
            return rc, False

    def terminate_tree(self, proc):
        with self._lock:
            state = self._states.get(proc)
            if not state or state["pid"] != proc.pid:
                raise ProcessContainmentUnavailable("untracked-process")
            if state["reaped"]:
                return
            info = self._observe_exit(proc, 0)
            if info is None:
                if not self._signal_group(proc, signal.SIGTERM):
                    raise ProcessContainmentUnavailable("process-group-term-failed")
            else:
                self._signal_after_leader_exit(proc, signal.SIGTERM)
            if info is None:
                info = self._observe_exit(proc, 0.5)
            if info is None:
                if not self._signal_group(proc, signal.SIGKILL):
                    raise ProcessContainmentUnavailable("process-group-kill-failed")
                info = self._observe_exit(proc, 1.0)
                if info is None:
                    raise ProcessContainmentUnavailable("leader-did-not-exit")
            # If leader exit was observed, it remains unreaped until this point.
            self._signal_after_leader_exit(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                raise ProcessContainmentUnavailable("leader-reap-timeout") from None
            state["reaped"] = True
